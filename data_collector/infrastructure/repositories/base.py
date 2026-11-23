"""Shared repository helpers for ObjectId parsing and document serialization."""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from data_collector.domain.entities import serialize_value
from data_collector.domain.exceptions import BadRequestError


def to_object_id(raw_id: str, field_name: str = "id") -> ObjectId:
    """Parse a 24-hex ObjectId string or raise BadRequestError."""
    try:
        return ObjectId(raw_id)
    except (InvalidId, TypeError) as exc:
        raise BadRequestError(f"Invalid {field_name} format") from exc


def serialize_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert MongoDB document to JSON-safe dict with string `id` instead of `_id`."""
    if doc is None:
        return None
    out: dict[str, Any] = {}
    for k, v in doc.items():
        if k == "_id":
            out["id"] = str(v)
        else:
            out[k] = serialize_value(v)
    return out
