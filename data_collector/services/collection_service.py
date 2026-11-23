"""Workspace, project, and collection/schema registry service."""

from __future__ import annotations

import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError as JsonSchemaError

from data_collector.domain.exceptions import NotFoundError, ValidationError
from data_collector.domain.identities import Actor, Scope
from data_collector.domain.policies import require_collection_policy, require_workspace_membership
from data_collector.infrastructure.repositories.tenant_repo import (
    CollectionRepository,
    ProjectRepository,
    WorkspaceRepository,
)
from data_collector.services.audit_service import AuditService

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")


def _validate_slug(slug: str, label: str = "slug") -> str:
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise ValidationError(f"Invalid {label}: use 3-64 lowercase alphanumeric, '-' or '_'")
    return slug


def _validate_json_schema(schema_json: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schema_json, dict):
        raise ValidationError("schema_json must be a JSON object")
    try:
        Draft202012Validator.check_schema(schema_json)
    except JsonSchemaError as exc:
        raise ValidationError(f"Invalid JSON Schema: {exc.message}") from exc
    return schema_json


class CollectionService:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRepository,
        projects: ProjectRepository,
        collections: CollectionRepository,
        audit: AuditService,
    ) -> None:
        self._workspaces = workspaces
        self._projects = projects
        self._collections = collections
        self._audit = audit

    def create_workspace(self, actor: Actor, *, slug: str, name: str) -> dict[str, Any]:
        _validate_slug(slug, "workspace slug")
        if not name or len(name) > 120:
            raise ValidationError("Workspace name must be 1-120 characters")
        ws = self._workspaces.create(slug, name.strip(), actor.principal_id)
        self._audit.record(
            tenant=ws["id"],
            actor_id=actor.principal_id,
            action="workspace.create",
            target=f"workspace:{ws['id']}",
            decision="allow",
        )
        return ws

    def list_workspaces(
        self, actor: Actor, limit: int = 25, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        return self._workspaces.list_for_principal(
            actor.principal_id, limit=min(limit, 100), cursor=cursor
        )

    def get_workspace(self, actor: Actor, workspace_id: str) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_READ)
        ws = self._workspaces.get_by_id(workspace_id)
        if ws is None:
            raise NotFoundError("Workspace not found")
        return ws

    def add_member(
        self, actor: Actor, workspace_id: str, principal_id: str, role_name: str
    ) -> None:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        if role_name not in {"admin", "editor", "viewer"}:
            raise ValidationError("Role must be admin, editor, or viewer")
        self._workspaces.set_membership(workspace_id, principal_id, role_name)
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="workspace.member_set",
            target=f"principal:{principal_id}",
            decision="allow",
            metadata={"role": role_name},
        )

    def create_project(
        self, actor: Actor, workspace_id: str, *, slug: str, name: str
    ) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.COLLECTION_MANAGE)
        _validate_slug(slug, "project slug")
        proj = self._projects.create(workspace_id, slug, name.strip())
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="project.create",
            target=f"project:{proj['id']}",
            decision="allow",
        )
        return proj

    def list_projects(self, actor: Actor, workspace_id: str) -> list[dict[str, Any]]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_READ)
        return self._projects.list_by_workspace(workspace_id)

    def create_collection(
        self,
        actor: Actor,
        project_id: str,
        *,
        slug: str,
        schema_json: dict[str, Any],
        searchable_fields: list[str] | None = None,
        sortable_fields: list[str] | None = None,
        retention_days: int = 30,
    ) -> dict[str, Any]:
        proj = self._projects.get_by_id(project_id)
        if proj is None:
            raise NotFoundError("Project not found")
        ws_id = proj["workspace_id"]
        role = self._workspaces.get_membership_role(ws_id, actor.principal_id)
        require_workspace_membership(actor, ws_id, role, Scope.COLLECTION_MANAGE)
        _validate_slug(slug, "collection slug")
        _validate_json_schema(schema_json)

        col = self._collections.create(
            ws_id,
            project_id,
            slug,
            schema_json,
            searchable_fields=searchable_fields,
            sortable_fields=sortable_fields,
            retention_days=retention_days,
        )
        self._audit.record(
            tenant=ws_id,
            actor_id=actor.principal_id,
            action="collection.create",
            target=f"collection:{col['id']}",
            decision="allow",
        )
        return col

    def list_collections(self, actor: Actor, project_id: str) -> list[dict[str, Any]]:
        proj = self._projects.get_by_id(project_id)
        if proj is None:
            raise NotFoundError("Project not found")
        ws_id = proj["workspace_id"]
        role = self._workspaces.get_membership_role(ws_id, actor.principal_id)
        require_workspace_membership(actor, ws_id, role, Scope.COLLECTION_READ)
        cols = self._collections.list_by_project(ws_id, project_id)
        if actor.allowed_collection_ids is not None:
            cols = [c for c in cols if c["id"] in actor.allowed_collection_ids]
        return cols

    def get_collection(
        self, actor: Actor, collection_id: str, required_scope: Scope = Scope.COLLECTION_READ
    ) -> dict[str, Any]:
        col = self._collections.get_by_id(collection_id)
        if col is None:
            raise NotFoundError("Collection not found")
        ws_id = col["workspace_id"]
        role = self._workspaces.get_membership_role(ws_id, actor.principal_id)
        allowed = (
            list(actor.allowed_collection_ids) if actor.allowed_collection_ids is not None else None
        )
        require_collection_policy(
            actor,
            ws_id,
            role,
            required_scope,
            allowed_collection_ids=allowed,
            collection_id=collection_id,
        )
        return col

    def update_collection(
        self,
        actor: Actor,
        collection_id: str,
        *,
        schema_json: dict[str, Any] | None = None,
        searchable_fields: list[str] | None = None,
        sortable_fields: list[str] | None = None,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        col = self.get_collection(actor, collection_id, required_scope=Scope.COLLECTION_MANAGE)
        if schema_json is not None:
            _validate_json_schema(schema_json)
        updated = self._collections.update_schema(
            col["workspace_id"],
            collection_id,
            schema_json=schema_json,
            searchable_fields=searchable_fields,
            sortable_fields=sortable_fields,
            retention_days=retention_days,
        )
        if updated is None:
            raise NotFoundError("Collection not found")
        self._audit.record(
            tenant=col["workspace_id"],
            actor_id=actor.principal_id,
            action="collection.update",
            target=f"collection:{collection_id}",
            decision="allow",
        )
        return updated
