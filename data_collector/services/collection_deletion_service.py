"""Two-step, audited hard deletion of a collection and everything that hangs off it.

Step 1 (`prepare`) reports what will be removed and issues a short-lived, single-use,
server-signed confirmation token bound to the actor, workspace, collection and slug.
Step 2 (`delete`) requires that token plus the slug typed back by the caller.

Why a hard delete rather than archive-then-purge: the project's soft-delete model is
per record (`records.deleted_at` + restore); there is no collection-level archive that
every read path honours, so an "archived" collection would still be readable and
writable through several services. A purge job would also leave hundreds of thousands
of dead rows in the shared `records` collection until it ran. Instead the collection
is first flagged `status="deleting"` (it disappears from listings and refuses reads
and writes through CollectionService), then its data is removed with bulk operations,
then the document itself is deleted. If the process dies midway the collection stays
hidden in the "deleting" state and the owner can simply prepare + delete again.
The audit event is the durable record of what was removed.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.database import Database

from data_collector.config import Settings
from data_collector.domain.entities import utc_now
from data_collector.domain.exceptions import (
    AuthorizationError,
    DomainError,
    NotFoundError,
    ValidationError,
)
from data_collector.domain.identities import Actor, Scope
from data_collector.domain.policies import require_workspace_membership
from data_collector.infrastructure.crypto import sign_intent_token, verify_intent_token
from data_collector.infrastructure.logging import get_request_id
from data_collector.infrastructure.repositories.record_repo import RecordRepository
from data_collector.infrastructure.repositories.tenant_repo import (
    ApiKeyRepository,
    CollectionRepository,
    DeleteIntentRepository,
    WorkspaceRepository,
)
from data_collector.services.audit_service import AuditService

CONFIRMATION_TTL_SECONDS = 300
_OP = "delete_collection"
_ACTIVE_JOB_STATES = ["queued", "running"]
_LIST_CAP = 50


class CollectionDeletionService:
    def __init__(
        self,
        *,
        settings: Settings,
        db: Database[Any],
        workspaces: WorkspaceRepository,
        collections: CollectionRepository,
        records: RecordRepository,
        api_keys: ApiKeyRepository,
        delete_intents: DeleteIntentRepository,
        audit: AuditService,
    ) -> None:
        self._settings = settings
        self._db = db
        self._workspaces = workspaces
        self._collections = collections
        self._records = records
        self._api_keys = api_keys
        self._intents = delete_intents
        self._audit = audit

    # ── helpers ───────────────────────────────────────────────────────────────
    def _deny(
        self,
        actor: Actor,
        *,
        action: str,
        collection_id: str,
        tenant: str | None,
        reason: str,
        correlation_id: str,
        slug: str | None = None,
    ) -> None:
        self._audit.record(
            tenant=tenant,
            actor_id=actor.principal_id,
            action=action,
            target=f"collection:{collection_id}",
            decision="deny",
            metadata={
                "reason": reason,
                "slug": slug,
                "correlation_id": correlation_id,
                "key_id": actor.key_id,
                "client_id": actor.client_id,
            },
        )

    def _load_and_authorize(
        self, actor: Actor, collection_id: str, *, action: str, correlation_id: str
    ) -> dict[str, Any]:
        col = self._collections.get_by_id(collection_id)
        if col is None:
            self._deny(
                actor,
                action=action,
                collection_id=collection_id,
                tenant=None,
                reason="not_found",
                correlation_id=correlation_id,
            )
            raise NotFoundError("Collection not found")
        ws_id = col["workspace_id"]
        try:
            if actor.is_mcp:
                raise AuthorizationError("Collection deletion is not available over MCP")
            if actor.allowed_collection_ids is not None:
                raise AuthorizationError("Collection-scoped API keys cannot delete collections")
            role = self._workspaces.get_membership_role(ws_id, actor.principal_id)
            require_workspace_membership(actor, ws_id, role, Scope.COLLECTION_DELETE)
        except (AuthorizationError, NotFoundError) as exc:
            self._deny(
                actor,
                action=action,
                collection_id=collection_id,
                tenant=ws_id,
                reason=exc.message,
                correlation_id=correlation_id,
                slug=col["slug"],
            )
            raise
        return col

    def _dependents(self, col: dict[str, Any]) -> dict[str, Any]:
        ws_id, cid = col["workspace_id"], col["id"]
        sq_filter = {"workspace_id": ws_id, "collection_id": cid}
        saved = [
            {"id": str(d["_id"]), "name": d.get("name")}
            for d in self._db.saved_queries.find(sq_filter, {"name": 1}).limit(_LIST_CAP)
        ]
        job_filter = {
            "workspace_id": ws_id,
            "params.collection_id": cid,
            "state": {"$in": _ACTIVE_JOB_STATES},
        }
        jobs = [
            {"id": str(d["_id"]), "type": d.get("type"), "state": d.get("state")}
            for d in self._db.jobs.find(job_filter, {"type": 1, "state": 1}).limit(_LIST_CAP)
        ]
        return {
            "records": self._records.count_for_collection(workspace_id=ws_id, collection_id=cid),
            "saved_queries": {
                "count": int(self._db.saved_queries.count_documents(sq_filter)),
                "items": saved,
            },
            "active_jobs": {
                "count": int(self._db.jobs.count_documents(job_filter)),
                "items": jobs,
            },
            "api_keys_restricted_to_collection": self._api_keys.count_restricted_to(ws_id, cid),
        }

    # ── step 1 ────────────────────────────────────────────────────────────────
    def prepare(self, actor: Actor, collection_id: str) -> dict[str, Any]:
        correlation_id = f"cdel_{secrets.token_hex(8)}"
        col = self._load_and_authorize(
            actor, collection_id, action="collection.delete_prepare", correlation_id=correlation_id
        )
        deps = self._dependents(col)
        token = sign_intent_token(
            {
                "op": _OP,
                "actor": actor.principal_id,
                "ws": col["workspace_id"],
                "cid": collection_id,
                "slug": col["slug"],
                "corr": correlation_id,
            },
            self._settings.intent_secret_key,
            ttl_seconds=CONFIRMATION_TTL_SECONDS,
        )
        decoded = verify_intent_token(token, self._settings.intent_secret_key)
        if decoded is None:  # pragma: no cover - defensive; just signed
            raise DomainError("Failed to issue confirmation token")
        self._intents.record_intent(
            str(decoded["jti"]), datetime.now(UTC) + timedelta(seconds=CONFIRMATION_TTL_SECONDS)
        )
        self._audit.record(
            tenant=col["workspace_id"],
            actor_id=actor.principal_id,
            action="collection.delete_prepare",
            target=f"collection:{collection_id}",
            decision="allow",
            metadata={
                "slug": col["slug"],
                "record_count": deps["records"],
                "saved_queries": deps["saved_queries"]["count"],
                "active_jobs": deps["active_jobs"]["count"],
                "correlation_id": correlation_id,
                "key_id": actor.key_id,
            },
        )
        return {
            "collection_id": collection_id,
            "workspace_id": col["workspace_id"],
            "project_id": col["project_id"],
            "slug": col["slug"],
            "status": col.get("status", "active"),
            **deps,
            "confirmation_token": token,
            "expires_in_seconds": CONFIRMATION_TTL_SECONDS,
            "correlation_id": correlation_id,
        }

    # ── step 2 ────────────────────────────────────────────────────────────────
    def delete(
        self,
        actor: Actor,
        collection_id: str,
        *,
        confirmation_token: str,
        confirm_slug: str,
    ) -> dict[str, Any]:
        action = "collection.delete"
        request_corr = get_request_id() or f"cdel_{secrets.token_hex(8)}"
        col = self._load_and_authorize(
            actor, collection_id, action=action, correlation_id=request_corr
        )
        ws_id = col["workspace_id"]
        slug = col["slug"]

        def deny(reason: str, corr: str, exc: DomainError) -> DomainError:
            self._deny(
                actor,
                action=action,
                collection_id=collection_id,
                tenant=ws_id,
                reason=reason,
                correlation_id=corr,
                slug=slug,
            )
            return exc

        decoded = verify_intent_token(confirmation_token, self._settings.intent_secret_key)
        if decoded is None:
            raise deny(
                "invalid_or_expired_token",
                request_corr,
                AuthorizationError("Invalid or expired confirmation_token"),
            )
        corr = str(decoded.get("corr") or request_corr)
        if (
            decoded.get("op") != _OP
            or decoded.get("actor") != actor.principal_id
            or decoded.get("ws") != ws_id
            or decoded.get("cid") != collection_id
        ):
            raise deny(
                "token_mismatch",
                corr,
                AuthorizationError("confirmation_token does not match actor or collection"),
            )
        if confirm_slug != slug or decoded.get("slug") != slug:
            raise deny(
                "slug_mismatch",
                corr,
                ValidationError("Typed slug does not match the collection slug"),
            )
        if not self._intents.consume(str(decoded["jti"])):
            raise deny(
                "token_already_used",
                corr,
                AuthorizationError("confirmation_token already used or unavailable"),
            )

        result: dict[str, Any] = {
            "records_deleted": 0,
            "saved_queries_deleted": 0,
            "jobs_cancelled": 0,
            "api_keys_detached": 0,
            "idempotency_keys_deleted": 0,
        }
        try:
            # 1. Hide the collection and stop new writes through CollectionService.
            self._collections.set_status(ws_id, collection_id, "deleting")
            # 2. Cancel queued/running import/export jobs that target it.
            jobs = self._db.jobs.update_many(
                {
                    "workspace_id": ws_id,
                    "params.collection_id": collection_id,
                    "state": {"$in": _ACTIVE_JOB_STATES},
                },
                {
                    "$set": {
                        "state": "cancelled",
                        "finished_at": utc_now(),
                        "error_summary": "Collection deleted",
                    }
                },
            )
            result["jobs_cancelled"] = int(jobs.modified_count)
            # 3. One bulk delete for all records, active and trashed.
            result["records_deleted"] = self._records.delete_all_for_collection(
                workspace_id=ws_id, collection_id=collection_id
            )
            # 4. Dependents.
            sq = self._db.saved_queries.delete_many(
                {"workspace_id": ws_id, "collection_id": collection_id}
            )
            result["saved_queries_deleted"] = int(sq.deleted_count)
            result["api_keys_detached"] = self._api_keys.detach_collection(ws_id, collection_id)
            idem = self._db.idempotency_keys.delete_many({"scope": f"{ws_id}:{collection_id}"})
            result["idempotency_keys_deleted"] = int(idem.deleted_count)
            # 5. The collection document, then sweep any record that raced in.
            self._collections.delete(ws_id, collection_id)
            result["records_deleted"] += self._records.delete_all_for_collection(
                workspace_id=ws_id, collection_id=collection_id
            )
        except Exception as exc:
            self._audit.record(
                tenant=ws_id,
                actor_id=actor.principal_id,
                action=action,
                target=f"collection:{collection_id}",
                decision="error",
                metadata={
                    "slug": slug,
                    "correlation_id": corr,
                    "error": type(exc).__name__,
                    **result,
                },
            )
            raise

        self._audit.record(
            tenant=ws_id,
            actor_id=actor.principal_id,
            action=action,
            target=f"collection:{collection_id}",
            decision="allow",
            metadata={
                "slug": slug,
                "project_id": col["project_id"],
                "record_count": result["records_deleted"],
                "correlation_id": corr,
                "key_id": actor.key_id,
                **result,
            },
        )
        return {
            "collection_id": collection_id,
            "slug": slug,
            "deleted": True,
            "correlation_id": corr,
            **result,
        }
