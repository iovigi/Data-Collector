"""Backend extensions service for Admin Dashboard (S1): capabilities, invitations, lifecycle."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import DESCENDING, ReturnDocument
from pymongo.database import Database

from data_collector.domain.entities import utc_now
from data_collector.domain.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from data_collector.domain.identities import Actor, Scope
from data_collector.domain.policies import (
    effective_scopes,
    parse_role,
    require_workspace_membership,
)
from data_collector.infrastructure.crypto import hash_token
from data_collector.infrastructure.repositories.base import serialize_doc, to_object_id
from data_collector.infrastructure.repositories.tenant_repo import (
    CollectionRepository,
    ProjectRepository,
    UserRepository,
    WorkspaceRepository,
)
from data_collector.infrastructure.ssrf import validate_outbound_url
from data_collector.services.audit_service import AuditService
from data_collector.services.collection_service import CollectionService
from data_collector.services.m11_service import ALLOWED_WEBHOOK_EVENTS
from data_collector.services.query_dsl import compile_filter
from data_collector.services.record_service import _allowed_fields_for_collection


class AdminExtensionService:
    """Service layer for admin UI endpoints, enforcing tenant isolation and RBAC."""

    def __init__(
        self,
        *,
        db: Database[Any],
        users: UserRepository,
        workspaces: WorkspaceRepository,
        projects: ProjectRepository,
        collections: CollectionRepository,
        collection_service: CollectionService,
        audit: AuditService,
        allow_localhost_dev: bool = False,
    ) -> None:
        self._db = db
        self._users = users
        self._workspaces = workspaces
        self._projects = projects
        self._collections = collections
        self._collection_service = collection_service
        self._audit = audit
        self._allow_localhost_dev = allow_localhost_dev

    # ── Capabilities ──────────────────────────────────────────────────────────
    def get_capabilities(self, actor: Actor, workspace_id: str) -> dict[str, Any]:
        role_str = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        role = require_workspace_membership(actor, workspace_id, role_str, Scope.WORKSPACE_READ)
        scopes = effective_scopes(actor, role)
        scope_vals = sorted(s.value for s in scopes)
        return {
            "workspace_id": workspace_id,
            "role": role.value,
            "scopes": scope_vals,
            "allowed_collection_ids": (
                sorted(actor.allowed_collection_ids)
                if actor.allowed_collection_ids is not None
                else None
            ),
            "features": {
                "can_manage_workspace": Scope.WORKSPACE_MANAGE in scopes,
                "can_manage_members": Scope.WORKSPACE_MANAGE in scopes,
                "can_create_keys": Scope.KEYS_MANAGE in scopes,
                "can_manage_collections": Scope.COLLECTION_MANAGE in scopes,
                "can_delete_collections": (
                    Scope.COLLECTION_DELETE in scopes
                    and actor.allowed_collection_ids is None
                    and not actor.is_mcp
                ),
                "can_write_records": Scope.RECORDS_WRITE in scopes,
                "can_delete_records": Scope.RECORDS_DELETE in scopes,
                "can_create_jobs": Scope.JOBS_CREATE in scopes,
                "can_export": Scope.EXPORT_READ in scopes,
                "can_read_audit": Scope.AUDIT_READ in scopes,
                "can_manage_webhooks": Scope.WORKSPACE_MANAGE in scopes,
            },
        }

    # ── Members & Invitations ─────────────────────────────────────────────────
    def list_members(
        self, actor: Actor, workspace_id: str, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_READ)
        query: dict[str, Any] = {"workspace_id": workspace_id}
        if cursor:
            query["_id"] = {"$gt": to_object_id(cursor, "cursor")}
        page_size = min(max(1, limit), 100)
        docs = list(self._db.memberships.find(query).sort("_id", 1).limit(page_size + 1))
        has_more = len(docs) > page_size
        rows = docs[:page_size]
        items: list[dict[str, Any]] = []
        for m in rows:
            u = self._users.find_by_id(str(m["principal_id"]))
            email = str(u["email"]) if u else None
            items.append(
                {
                    "id": str(m["_id"]),
                    "principal_id": str(m["principal_id"]),
                    "email": email,
                    "role": str(m["role"]),
                    "joined_at": serialize_doc({"ts": m.get("created_at")})["ts"],  # type: ignore[index]
                }
            )
        next_cursor = str(rows[-1]["_id"]) if has_more and rows else None
        return {"items": items, "next_cursor": next_cursor, "has_more": has_more}

    def update_member_role(
        self, actor: Actor, workspace_id: str, target_principal_id: str, new_role: str
    ) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        if new_role not in {"admin", "editor", "viewer"}:
            raise ValidationError(
                "Role must be admin, editor, or viewer (use transfer-ownership for owner)"
            )
        current = self._workspaces.get_membership_role(workspace_id, target_principal_id)
        if current is None:
            raise NotFoundError("Member not found")
        if current == "owner":
            owners = self._db.memberships.count_documents(
                {"workspace_id": workspace_id, "role": "owner"}
            )
            if owners <= 1:
                raise ConflictError("Cannot demote the last workspace owner")
        self._workspaces.set_membership(workspace_id, target_principal_id, new_role)
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="member.role_update",
            target=f"principal:{target_principal_id}",
            decision="allow",
            metadata={"new_role": new_role},
        )
        return {"principal_id": target_principal_id, "role": new_role}

    def remove_member(self, actor: Actor, workspace_id: str, target_principal_id: str) -> None:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        current = self._workspaces.get_membership_role(workspace_id, target_principal_id)
        if current is None:
            raise NotFoundError("Member not found")
        if current == "owner":
            owners = self._db.memberships.count_documents(
                {"workspace_id": workspace_id, "role": "owner"}
            )
            if owners <= 1:
                raise ConflictError("Cannot remove the last workspace owner")
        self._db.memberships.delete_one(
            {"workspace_id": workspace_id, "principal_id": target_principal_id}
        )
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="member.remove",
            target=f"principal:{target_principal_id}",
            decision="allow",
        )

    def transfer_ownership(
        self, actor: Actor, workspace_id: str, target_principal_id: str
    ) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        if parse_role(role or "") != parse_role("owner"):
            raise AuthorizationError("Only an owner can transfer workspace ownership")
        target_role = self._workspaces.get_membership_role(workspace_id, target_principal_id)
        if target_role is None:
            raise NotFoundError("Target user must already be a workspace member")
        target_user = self._users.find_by_id(target_principal_id)
        if target_user is None or target_user.get("status") != "active":
            raise ValidationError("Target user is not active")
        self._workspaces.set_membership(workspace_id, target_principal_id, "owner")
        self._workspaces.set_membership(workspace_id, actor.principal_id, "admin")
        self._db.workspaces.update_one(
            {"_id": to_object_id(workspace_id, "workspace_id")},
            {"$set": {"owner_id": target_principal_id}},
        )
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="workspace.transfer_ownership",
            target=f"principal:{target_principal_id}",
            decision="allow",
        )
        return {"workspace_id": workspace_id, "new_owner_id": target_principal_id}

    def create_invitation(
        self, actor: Actor, workspace_id: str, *, email: str, role_name: str
    ) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        if role_name not in {"admin", "editor", "viewer"}:
            raise ValidationError("Invited role must be admin, editor, or viewer")
        normalized_email = email.strip().lower()
        if "@" not in normalized_email or len(normalized_email) < 5:
            raise ValidationError("Valid email address is required")
        raw_token = secrets.token_urlsafe(32)
        now = utc_now()
        doc = {
            "workspace_id": workspace_id,
            "email": normalized_email,
            "role": role_name,
            "token_hash": hash_token(raw_token),
            "status": "pending",
            "invited_by": actor.principal_id,
            "created_at": now,
            "expires_at": now + timedelta(days=7),
            "accepted_at": None,
        }
        res = self._db.invitations.insert_one(doc)
        doc["_id"] = res.inserted_id
        out = serialize_doc(doc)
        assert out is not None
        out.pop("token_hash", None)
        out["invite_token"] = raw_token
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="invitation.create",
            target=f"invitation:{out['id']}",
            decision="allow",
        )
        return out

    def list_invitations(self, actor: Actor, workspace_id: str) -> list[dict[str, Any]]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        docs = list(
            self._db.invitations.find({"workspace_id": workspace_id}).sort("created_at", DESCENDING)
        )
        out = []
        for d in docs:
            s = serialize_doc(d)
            if s:
                s.pop("token_hash", None)
                out.append(s)
        return out

    def accept_invitation(self, actor: Actor, invitation_id: str, token: str) -> dict[str, Any]:
        oid = to_object_id(invitation_id, "invitation_id")
        inv = self._db.invitations.find_one({"_id": oid})
        if inv is None or inv.get("status") != "pending":
            raise NotFoundError("Invitation not found or no longer pending")
        exp = inv["expires_at"]
        if isinstance(exp, datetime):
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp < utc_now():
                raise ValidationError("Invitation has expired")
        if hash_token(token) != inv.get("token_hash"):
            raise AuthorizationError("Invalid invitation token")
        user = self._users.find_by_id(actor.principal_id)
        if user is None or str(user.get("email", "")).lower() != str(inv["email"]).lower():
            raise AuthorizationError("Invitation email does not match authenticated user")

        consumed = self._db.invitations.find_one_and_update(
            {"_id": oid, "status": "pending"},
            {"$set": {"status": "accepted", "accepted_at": utc_now()}},
        )
        if consumed is None:
            raise ConflictError("Invitation already accepted")
        ws_id = str(inv["workspace_id"])
        self._workspaces.set_membership(ws_id, actor.principal_id, str(inv["role"]))
        self._audit.record(
            tenant=ws_id,
            actor_id=actor.principal_id,
            action="invitation.accept",
            target=f"invitation:{invitation_id}",
            decision="allow",
        )
        return {"workspace_id": ws_id, "role": str(inv["role"]), "status": "accepted"}

    def revoke_invitation(self, actor: Actor, invitation_id: str) -> dict[str, Any]:
        oid = to_object_id(invitation_id, "invitation_id")
        inv = self._db.invitations.find_one({"_id": oid})
        if inv is None:
            raise NotFoundError("Invitation not found")
        ws_id = str(inv["workspace_id"])
        role = self._workspaces.get_membership_role(ws_id, actor.principal_id)
        require_workspace_membership(actor, ws_id, role, Scope.WORKSPACE_MANAGE)
        doc = self._db.invitations.find_one_and_update(
            {"_id": oid, "workspace_id": ws_id},
            {"$set": {"status": "revoked"}},
            return_document=ReturnDocument.AFTER,
        )
        s = serialize_doc(doc)
        if s:
            s.pop("token_hash", None)
        return s or {}

    # ── Workspace & Project Lifecycle ─────────────────────────────────────────
    def update_workspace(self, actor: Actor, workspace_id: str, *, name: str) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        if not name.strip() or len(name.strip()) > 120:
            raise ValidationError("Workspace name must be 1-120 characters")
        doc = self._db.workspaces.find_one_and_update(
            {"_id": to_object_id(workspace_id, "workspace_id")},
            {"$set": {"name": name.strip()}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            raise NotFoundError("Workspace not found")
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="workspace.update",
            target=f"workspace:{workspace_id}",
            decision="allow",
        )
        return serialize_doc(doc)  # type: ignore[return-value]

    def set_workspace_status(self, actor: Actor, workspace_id: str, status: str) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        doc = self._db.workspaces.find_one_and_update(
            {"_id": to_object_id(workspace_id, "workspace_id")},
            {"$set": {"status": status}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            raise NotFoundError("Workspace not found")
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action=f"workspace.{status}",
            target=f"workspace:{workspace_id}",
            decision="allow",
        )
        return serialize_doc(doc)  # type: ignore[return-value]

    def get_project(self, actor: Actor, project_id: str) -> dict[str, Any]:
        proj = self._projects.get_by_id(project_id)
        if proj is None:
            raise NotFoundError("Project not found")
        role = self._workspaces.get_membership_role(proj["workspace_id"], actor.principal_id)
        require_workspace_membership(actor, proj["workspace_id"], role, Scope.WORKSPACE_READ)
        return proj

    def update_project(
        self, actor: Actor, project_id: str, *, name: str | None = None, status: str | None = None
    ) -> dict[str, Any]:
        proj = self.get_project(actor, project_id)
        ws_id = proj["workspace_id"]
        role = self._workspaces.get_membership_role(ws_id, actor.principal_id)
        require_workspace_membership(actor, ws_id, role, Scope.COLLECTION_MANAGE)
        updates: dict[str, Any] = {}
        if name is not None:
            if not name.strip() or len(name.strip()) > 120:
                raise ValidationError("Project name must be 1-120 characters")
            updates["name"] = name.strip()
        if status is not None:
            updates["status"] = status
        if not updates:
            return proj
        doc = self._db.projects.find_one_and_update(
            {"_id": to_object_id(project_id, "project_id"), "workspace_id": ws_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        self._audit.record(
            tenant=ws_id,
            actor_id=actor.principal_id,
            action="project.update",
            target=f"project:{project_id}",
            decision="allow",
        )
        return serialize_doc(doc)  # type: ignore[return-value]

    # ── Paginated Jobs, Audit & Trash ─────────────────────────────────────────
    def list_workspace_jobs(
        self,
        actor: Actor,
        workspace_id: str,
        *,
        state: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.JOBS_READ)
        query: dict[str, Any] = {"workspace_id": workspace_id}
        if state:
            query["state"] = state
        if job_type:
            query["type"] = job_type
        if cursor:
            query["_id"] = {"$lt": to_object_id(cursor, "cursor")}
        page_size = min(max(1, limit), 100)
        docs = list(self._db.jobs.find(query).sort("_id", DESCENDING).limit(page_size + 1))
        has_more = len(docs) > page_size
        rows = [s for d in docs[:page_size] if (s := serialize_doc(d)) is not None]
        next_cursor = rows[-1]["id"] if has_more and rows else None
        return {"items": rows, "next_cursor": next_cursor, "has_more": has_more}

    def list_workspace_audit_paginated(
        self,
        actor: Actor,
        workspace_id: str,
        *,
        actor_id: str | None = None,
        action: str | None = None,
        decision: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.AUDIT_READ)
        query: dict[str, Any] = {"tenant": workspace_id}
        if actor_id:
            query["actor"] = actor_id
        if action:
            query["action"] = action
        if decision:
            query["decision"] = decision
        if cursor:
            query["_id"] = {"$lt": to_object_id(cursor, "cursor")}
        page_size = min(max(1, limit), 100)
        docs = list(self._db.audit_events.find(query).sort("_id", DESCENDING).limit(page_size + 1))
        has_more = len(docs) > page_size
        rows = [s for d in docs[:page_size] if (s := serialize_doc(d)) is not None]
        next_cursor = rows[-1]["id"] if has_more and rows else None
        return {"items": rows, "next_cursor": next_cursor, "has_more": has_more}

    def list_record_trash(
        self,
        actor: Actor,
        collection_id: str,
        *,
        limit: int = 25,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        col = self._collection_service.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_READ
        )
        query: dict[str, Any] = {
            "workspace_id": col["workspace_id"],
            "project_id": col["project_id"],
            "collection_id": collection_id,
            "deleted_at": {"$ne": None},
        }
        if cursor:
            query["_id"] = {"$lt": to_object_id(cursor, "cursor")}
        page_size = min(max(1, limit), 100)
        docs = list(self._db.records.find(query).sort("_id", DESCENDING).limit(page_size + 1))
        has_more = len(docs) > page_size
        rows = [s for d in docs[:page_size] if (s := serialize_doc(d)) is not None]
        next_cursor = rows[-1]["id"] if has_more and rows else None
        return {"items": rows, "next_cursor": next_cursor, "has_more": has_more}

    # ── Saved Queries & Webhooks Full Management ──────────────────────────────
    def get_saved_query(self, actor: Actor, sq_id: str) -> dict[str, Any]:
        sq = serialize_doc(
            self._db.saved_queries.find_one({"_id": to_object_id(sq_id, "saved_query_id")})
        )
        if sq is None:
            raise NotFoundError("Saved query not found")
        self._collection_service.get_collection(
            actor, sq["collection_id"], required_scope=Scope.COLLECTION_READ
        )
        return sq

    def update_saved_query(
        self,
        actor: Actor,
        sq_id: str,
        *,
        name: str | None = None,
        filter_ast: dict[str, Any] | None = None,
        sort: list[dict[str, str]] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        sq = self.get_saved_query(actor, sq_id)
        col = self._collection_service.get_collection(
            actor, sq["collection_id"], required_scope=Scope.COLLECTION_MANAGE
        )
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if name is not None:
            updates["name"] = name.strip()
        if filter_ast is not None:
            compile_filter(filter_ast, allowed_fields=_allowed_fields_for_collection(col))
            updates["filter"] = filter_ast
        if sort is not None:
            updates["sort"] = sort
        if fields is not None:
            updates["fields"] = fields
        if limit is not None:
            updates["limit"] = min(max(1, limit), 100)
        doc = self._db.saved_queries.find_one_and_update(
            {"_id": to_object_id(sq_id, "saved_query_id")},
            {"$set": updates, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        )
        return serialize_doc(doc)  # type: ignore[return-value]

    def delete_saved_query(self, actor: Actor, sq_id: str) -> None:
        sq = self.get_saved_query(actor, sq_id)
        self._collection_service.get_collection(
            actor, sq["collection_id"], required_scope=Scope.COLLECTION_MANAGE
        )
        self._db.saved_queries.delete_one({"_id": to_object_id(sq_id, "saved_query_id")})

    def get_webhook(self, actor: Actor, workspace_id: str, hook_id: str) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_READ)
        doc = self._db.webhooks.find_one(
            {"_id": to_object_id(hook_id, "webhook_id"), "workspace_id": workspace_id}
        )
        s = serialize_doc(doc)
        if s is None:
            raise NotFoundError("Webhook not found")
        s.pop("secret_hash", None)
        s.pop("signing_secret_enc", None)
        return s

    def update_webhook(
        self,
        actor: Actor,
        workspace_id: str,
        hook_id: str,
        *,
        name: str | None = None,
        url: str | None = None,
        events: list[str] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name.strip()
        if url is not None:
            validate_outbound_url(url, allow_localhost_dev=self._allow_localhost_dev)
            updates["url"] = url
        if events is not None:
            for ev in events:
                if ev not in ALLOWED_WEBHOOK_EVENTS:
                    raise ValidationError(f"Unsupported webhook event '{ev}'")
            updates["events"] = list(dict.fromkeys(events))
        if status is not None:
            if status not in {"active", "disabled"}:
                raise ValidationError("Webhook status must be active or disabled")
            updates["status"] = status
        doc = self._db.webhooks.find_one_and_update(
            {"_id": to_object_id(hook_id, "webhook_id"), "workspace_id": workspace_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        s = serialize_doc(doc)
        if s is None:
            raise NotFoundError("Webhook not found")
        s.pop("secret_hash", None)
        s.pop("signing_secret_enc", None)
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="webhook.update",
            target=f"webhook:{hook_id}",
            decision="allow",
        )
        return s

    def delete_webhook(self, actor: Actor, workspace_id: str, hook_id: str) -> None:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        res = self._db.webhooks.delete_one(
            {"_id": to_object_id(hook_id, "webhook_id"), "workspace_id": workspace_id}
        )
        if res.deleted_count == 0:
            raise NotFoundError("Webhook not found")
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="webhook.delete",
            target=f"webhook:{hook_id}",
            decision="allow",
        )

    def rotate_webhook_secret(
        self, actor: Actor, workspace_id: str, hook_id: str
    ) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        new_secret = f"whsec_{secrets.token_urlsafe(32)}"
        doc = self._db.webhooks.find_one_and_update(
            {"_id": to_object_id(hook_id, "webhook_id"), "workspace_id": workspace_id},
            {
                "$set": {
                    "signing_secret_enc": new_secret,
                    "secret_hash": hash_token(new_secret),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        s = serialize_doc(doc)
        if s is None:
            raise NotFoundError("Webhook not found")
        s.pop("secret_hash", None)
        s.pop("signing_secret_enc", None)
        s["signing_secret"] = new_secret
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="webhook.rotate_secret",
            target=f"webhook:{hook_id}",
            decision="allow",
        )
        return s

    def list_webhook_deliveries(
        self, actor: Actor, workspace_id: str, hook_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        self.get_webhook(actor, workspace_id, hook_id)
        docs = list(
            self._db.webhook_deliveries.find({"workspace_id": workspace_id, "webhook_id": hook_id})
            .sort("_id", DESCENDING)
            .limit(min(max(1, limit), 100))
        )
        return [s for d in docs if (s := serialize_doc(d)) is not None]

    # ── Dashboard Summary ─────────────────────────────────────────────────────
    def dashboard_summary(self, actor: Actor, workspace_id: str) -> dict[str, Any]:
        role_str = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        role = require_workspace_membership(actor, workspace_id, role_str, Scope.WORKSPACE_READ)
        scopes = effective_scopes(actor, role)
        projects = self._projects.list_by_workspace(workspace_id, limit=5)
        recent_jobs = (
            self.list_workspace_jobs(actor, workspace_id, limit=5)["items"]
            if Scope.JOBS_READ in scopes
            else []
        )
        return {
            "workspace_id": workspace_id,
            "counts": {
                "records_active": self._db.records.count_documents(
                    {"workspace_id": workspace_id, "deleted_at": None}
                ),
                "projects": self._db.projects.count_documents({"workspace_id": workspace_id}),
                "collections": self._db.collections.count_documents({"workspace_id": workspace_id}),
                "jobs_completed": self._db.jobs.count_documents(
                    {"workspace_id": workspace_id, "state": "completed"}
                ),
                "jobs_failed": self._db.jobs.count_documents(
                    {"workspace_id": workspace_id, "state": "failed"}
                ),
                "audit_events": (
                    self._db.audit_events.count_documents({"tenant": workspace_id})
                    if Scope.AUDIT_READ in scopes
                    else None
                ),
            },
            "recent_projects": projects,
            "recent_jobs": recent_jobs,
        }
