"""Domain entity models and serialization helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import Binary, Decimal128, ObjectId
from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(UTC)


def serialize_value(val: Any) -> Any:
    """Deterministically serialize MongoDB/BSON types to JSON-safe primitives."""
    if isinstance(val, ObjectId):
        return str(val)
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=UTC)
        return val.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(val, Decimal128):
        return str(val.to_decimal())
    if isinstance(val, Binary | bytes):
        raise ValueError("Binary values are not permitted in JSON responses")
    if isinstance(val, dict):
        return {str(k): serialize_value(v) for k, v in val.items()}
    if isinstance(val, list):
        return [serialize_value(item) for item in val]
    return val


class WorkspaceDTO(BaseModel):
    id: str
    slug: str
    name: str
    owner_id: str
    status: str = "active"
    created_at: datetime


class ProjectDTO(BaseModel):
    id: str
    workspace_id: str
    slug: str
    name: str
    status: str = "active"
    created_at: datetime


class CollectionDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    workspace_id: str
    project_id: str
    slug: str
    json_schema: dict[str, Any] = Field(default_factory=dict, alias="schema_json")
    schema_version: int = 1
    searchable_fields: list[str] = Field(default_factory=list)
    sortable_fields: list[str] = Field(default_factory=list)
    retention_days: int = 30
    status: str = "active"
    created_at: datetime


class RecordDTO(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    collection_id: str
    data: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime
    created_by: str
    deleted_at: datetime | None = None
    source: dict[str, Any] = Field(default_factory=dict)
