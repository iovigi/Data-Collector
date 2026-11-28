"""Safe Query DSL compiler and tenant-bound cursor codec.

Prohibits raw MongoDB operators ($where, $expr, $regex, $lookup, etc.) and
enforces depth, branch, field-allowlist, and payload bounds.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from data_collector.domain.exceptions import ValidationError

ALLOWED_OPS = frozenset(
    {"eq", "ne", "gt", "gte", "lt", "lte", "in", "exists", "contains", "array_contains", "between"}
)
BUILTIN_METADATA_FIELDS = frozenset({"created_at", "updated_at", "version", "id"})
FORBIDDEN_SEGMENTS = frozenset({"__proto__", "constructor", "prototype"})
MAX_DEPTH = 4
MAX_BRANCHES = 20
MAX_FILTER_BYTES = 16 * 1024
MAX_IN_ITEMS = 50
MAX_CONTAINS_LEN = 200
_FIELD_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")


def validate_field_name(field: str, allowed_fields: set[str] | None = None) -> str:
    """Validate field path against injection patterns and optional schema allowlist."""
    if not isinstance(field, str) or not field or len(field) > 128:
        raise ValidationError(
            "Invalid field name", details=[{"path": "field", "reason": "invalid"}]
        )
    if "$" in field or "\x00" in field or not _FIELD_RE.match(field):
        raise ValidationError(
            "Field name contains disallowed characters",
            details=[{"path": field, "reason": "disallowed syntax"}],
        )
    for seg in field.split("."):
        if seg in FORBIDDEN_SEGMENTS:
            raise ValidationError(
                "Forbidden field segment",
                details=[{"path": field, "reason": "forbidden segment"}],
            )
    if (
        allowed_fields is not None
        and field not in allowed_fields
        and field not in BUILTIN_METADATA_FIELDS
        # A dotted path inside an allowed top-level property (e.g. dc_event.observed_at
        # when dc_event is a schema property) addresses the same data, so it is allowed.
        and field.split(".", 1)[0] not in allowed_fields
    ):
        raise ValidationError(
            f"Field '{field}' is not in collection allowlist",
            details=[{"path": field, "reason": "not allowed"}],
        )
    return field


DATETIME_METADATA_FIELDS = frozenset({"created_at", "updated_at"})


def parse_iso_datetime(value: Any) -> Any:
    """Parse an ISO-8601 string (``Z`` suffix allowed) to an aware UTC datetime.

    Non-string or unparseable values are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _coerce_scalar(field: str, val: Any) -> Any:
    """Convert filter values for metadata fields to their stored BSON types."""
    if field == "id" and isinstance(val, str):
        try:
            return ObjectId(val)
        except Exception as exc:
            raise ValidationError("Invalid id value") from exc
    if field in DATETIME_METADATA_FIELDS and isinstance(val, str):
        parsed = parse_iso_datetime(val)
        if not isinstance(parsed, datetime):
            raise ValidationError(
                f"'{field}' value must be an ISO-8601 date/time",
                details=[{"path": field, "reason": "invalid datetime"}],
            )
        return parsed
    return val


def _to_mongo_field(field: str) -> str:
    if field == "id":
        return "_id"
    if field in BUILTIN_METADATA_FIELDS:
        return field
    return f"data.{field}"


def compile_filter(
    node: dict[str, Any] | None,
    *,
    allowed_fields: set[str] | None = None,
) -> dict[str, Any]:
    """Compile a Safe Query DSL AST into a MongoDB filter dict."""
    if not node:
        return {}
    raw_bytes = len(json.dumps(node, default=str).encode("utf-8"))
    if raw_bytes > MAX_FILTER_BYTES:
        raise ValidationError("Filter exceeds maximum 16 KiB size")

    branch_counter = {"count": 0}

    def _compile(cur: Any, depth: int) -> dict[str, Any]:
        if depth > MAX_DEPTH:
            raise ValidationError(f"Filter nesting exceeds max depth {MAX_DEPTH}")
        if not isinstance(cur, dict) or not cur:
            raise ValidationError("Filter node must be a non-empty object")

        for k in cur:
            if str(k).startswith("$"):
                raise ValidationError(f"Raw MongoDB operator '{k}' is prohibited")

        if "and" in cur:
            items = cur["and"]
            if not isinstance(items, list) or not items or len(cur) > 1:
                raise ValidationError("'and' must be a non-empty array")
            return {"$and": [_compile(item, depth + 1) for item in items]}

        if "or" in cur:
            items = cur["or"]
            if not isinstance(items, list) or not items or len(cur) > 1:
                raise ValidationError("'or' must be a non-empty array")
            return {"$or": [_compile(item, depth + 1) for item in items]}

        if "not" in cur:
            if len(cur) > 1:
                raise ValidationError("'not' must be the sole key in its node")
            return {"$nor": [_compile(cur["not"], depth + 1)]}

        branch_counter["count"] += 1
        if branch_counter["count"] > MAX_BRANCHES:
            raise ValidationError(f"Filter exceeds max {MAX_BRANCHES} predicates")

        field = cur.get("field")
        op = cur.get("op")
        if not isinstance(field, str) or not isinstance(op, str):
            raise ValidationError("Predicate requires 'field' and 'op'")
        if op not in ALLOWED_OPS:
            raise ValidationError(f"Operator '{op}' is not allowed")

        validate_field_name(field, allowed_fields)
        mongo_field = _to_mongo_field(field)
        val = cur.get("value")

        if isinstance(val, dict) and any(str(k).startswith("$") for k in val):
            raise ValidationError("MongoDB operator objects are not allowed in predicate values")

        if op in {"eq", "ne", "gt", "gte", "lt", "lte"}:
            val = _coerce_scalar(field, val)
        elif op == "in" and isinstance(val, list):
            val = [_coerce_scalar(field, v) for v in val]

        if op == "eq":
            return {mongo_field: val}
        if op == "ne":
            return {mongo_field: {"$ne": val}}
        if op == "gt":
            return {mongo_field: {"$gt": val}}
        if op == "gte":
            return {mongo_field: {"$gte": val}}
        if op == "lt":
            return {mongo_field: {"$lt": val}}
        if op == "lte":
            return {mongo_field: {"$lte": val}}
        if op == "in":
            if not isinstance(val, list) or len(val) > MAX_IN_ITEMS:
                raise ValidationError(f"'in' value must be a list of <= {MAX_IN_ITEMS} items")
            return {mongo_field: {"$in": val}}
        if op == "exists":
            return {mongo_field: {"$exists": bool(val)}}
        if op == "contains":
            if not isinstance(val, str) or len(val) > MAX_CONTAINS_LEN:
                raise ValidationError(
                    f"'contains' value must be a string <= {MAX_CONTAINS_LEN} chars"
                )
            escaped = re.escape(val)
            return {mongo_field: {"$regex": escaped, "$options": "i"}}
        if op == "array_contains":
            if isinstance(val, (dict, list)):
                raise ValidationError("'array_contains' value must be a scalar")
            val = _coerce_scalar(field, val)
            return {mongo_field: val}
        if op == "between":
            if not isinstance(val, list) or len(val) != 2:
                raise ValidationError("'between' value must be a 2-element [min, max] array")
            low = _coerce_scalar(field, val[0])
            high = _coerce_scalar(field, val[1])
            return {mongo_field: {"$gte": low, "$lte": high}}

        raise ValidationError(f"Unsupported operator '{op}'")

    return _compile(node, 1)


def iter_filter_predicates(node: dict[str, Any] | None) -> list[tuple[str, str, Any]]:
    """Extract all (field, op, value) predicates from a validated Safe Query DSL AST."""
    if not node:
        return []
    out: list[tuple[str, str, Any]] = []

    def _walk(cur: Any) -> None:
        if not isinstance(cur, dict):
            return
        if "and" in cur and isinstance(cur["and"], list):
            for item in cur["and"]:
                _walk(item)
            return
        if "or" in cur and isinstance(cur["or"], list):
            for item in cur["or"]:
                _walk(item)
            return
        if "not" in cur:
            _walk(cur["not"])
            return
        field = cur.get("field")
        op = cur.get("op")
        if isinstance(field, str) and isinstance(op, str):
            out.append((field, op, cur.get("value")))

    _walk(node)
    return out


def compile_projection(
    fields: list[str] | None,
    *,
    allowed_fields: set[str] | None = None,
) -> dict[str, int] | None:
    """Compile requested field projection; returns None for full record."""
    if not fields:
        return None
    proj: dict[str, int] = {
        "_id": 1,
        "workspace_id": 1,
        "project_id": 1,
        "collection_id": 1,
        "version": 1,
        "created_at": 1,
        "updated_at": 1,
        "created_by": 1,
        "deleted_at": 1,
        "source": 1,
    }
    for f in fields:
        validate_field_name(f, allowed_fields)
        if f not in BUILTIN_METADATA_FIELDS:
            proj[f"data.{f}"] = 1
    return proj


def query_signature(
    workspace_id: str,
    collection_id: str,
    filter_ast: dict[str, Any] | None,
    sort_field: str,
    sort_dir: str,
) -> str:
    raw = json.dumps(
        {
            "w": workspace_id,
            "c": collection_id,
            "f": filter_ast or {},
            "sf": sort_field,
            "sd": sort_dir,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def encode_cursor(
    *,
    secret: str,
    sig: str,
    sort_value: Any,
    last_id: str,
) -> str:
    payload: dict[str, Any] = {"s": sig, "id": last_id}
    if isinstance(sort_value, datetime):
        payload["v"] = sort_value.isoformat()
        payload["vt"] = "dt"
    else:
        payload["v"] = sort_value
        payload["vt"] = "raw"
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")
    b64 = urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    mac = hmac.new(secret.encode("utf-8"), b64.encode("ascii"), hashlib.sha256).hexdigest()[:16]
    return f"{b64}.{mac}"


def decode_cursor_payload(
    *,
    cursor: str,
    secret: str,
    expected_sig: str,
) -> dict[str, Any]:
    """Decode the payload and verify its signature and query binding."""
    try:
        b64, mac = cursor.split(".", 1)
    except ValueError as exc:
        raise ValidationError("Invalid pagination cursor") from exc
    expected_mac = hmac.new(
        secret.encode("utf-8"), b64.encode("ascii"), hashlib.sha256
    ).hexdigest()[:16]
    if not hmac.compare_digest(mac, expected_mac):
        raise ValidationError("Invalid pagination cursor signature")
    padded = b64 + "=" * (-len(b64) % 4)
    try:
        payload = json.loads(urlsafe_b64decode(padded).decode("utf-8"))
    except Exception as exc:
        raise ValidationError("Malformed pagination cursor") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Malformed pagination cursor")
    if payload.get("s") != expected_sig:
        raise ValidationError("Cursor does not match collection or query parameters")

    return payload


def decode_cursor(
    *,
    cursor: str,
    secret: str,
    expected_sig: str,
    sort_field: str,
    sort_direction: int,
) -> dict[str, Any]:
    """Decode the cursor and return a MongoDB keyset filter."""
    payload = decode_cursor_payload(cursor=cursor, secret=secret, expected_sig=expected_sig)
    last_oid = ObjectId(payload["id"])
    cmp_op = "$gt" if sort_direction >= 0 else "$lt"
    if sort_field == "_id":
        return {"_id": {cmp_op: last_oid}}

    sort_val = payload.get("v")
    if payload.get("vt") == "dt" and isinstance(sort_val, str):
        sort_val = datetime.fromisoformat(sort_val.replace("Z", "+00:00"))

    return {
        "$or": [
            {sort_field: {cmp_op: sort_val}},
            {sort_field: sort_val, "_id": {cmp_op: last_oid}},
        ]
    }
