"""Pydantic v2 request/response DTOs for Data API v1."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class CreateWorkspaceRequest(BaseModel):
    slug: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=120)


class AddMemberRequest(BaseModel):
    principal_id: str = Field(min_length=1)
    role: str = Field(pattern="^(admin|editor|viewer)$")


class CreateProjectRequest(BaseModel):
    slug: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=120)


class CreateCollectionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    slug: str = Field(min_length=3, max_length=64)
    json_schema: dict[str, Any] = Field(default_factory=dict, alias="schema_json")
    searchable_fields: list[str] = Field(default_factory=list)
    sortable_fields: list[str] = Field(default_factory=lambda: ["created_at", "updated_at"])
    retention_days: int = Field(default=30, ge=1, le=3650)


class UpdateCollectionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    json_schema: dict[str, Any] | None = Field(default=None, alias="schema_json")
    searchable_fields: list[str] | None = None
    sortable_fields: list[str] | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class CreateRecordRequest(BaseModel):
    data: dict[str, Any]


class BatchCreateRecordsRequest(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1)


class UpdateRecordRequest(BaseModel):
    patch: dict[str, Any]
    expected_version: int = Field(ge=1)


class DeleteCollectionRequest(BaseModel):
    confirmation_token: str = Field(min_length=1, max_length=4096)
    confirm_slug: str = Field(min_length=1, max_length=64)


class DeleteRecordRequest(BaseModel):
    expected_version: int = Field(ge=1)


class SortSpec(BaseModel):
    field: str = Field(min_length=1, max_length=128)
    direction: str = Field(default="desc", pattern="^(asc|desc)$")


class SearchRecordsRequest(BaseModel):
    filter: dict[str, Any] | None = None
    sort: list[SortSpec] | None = None
    fields: list[str] | None = None
    limit: int = Field(default=25, ge=1, le=100)
    cursor: str | None = None


class CreateApiKeyRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1)
    allowed_collection_ids: list[str] | None = None
    expires_in_days: int = Field(default=90, ge=1, le=365)
