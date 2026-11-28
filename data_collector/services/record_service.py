"""Record CRUD, schema validation, optimistic concurrency, safe search, and idempotency."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from data_collector.config import Settings
from data_collector.domain.exceptions import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    QueryNotIndexedError,
    ValidationError,
)
from data_collector.domain.identities import Actor, Scope
from data_collector.infrastructure.crypto import hash_token
from data_collector.infrastructure.logging import get_request_id
from data_collector.infrastructure.repositories.record_repo import RecordRepository
from data_collector.infrastructure.repositories.tenant_repo import IdempotencyRepository
from data_collector.services.audit_service import AuditService
from data_collector.services.collection_service import CollectionService
from data_collector.services.query_dsl import (
    compile_filter,
    compile_projection,
    decode_cursor,
    encode_cursor,
    parse_iso_datetime,
    query_signature,
    validate_field_name,
)
from data_collector.services.search_planner import plan_search

_RESERVED_DATA_KEYS = frozenset(
    {"_id", "workspace_id", "project_id", "collection_id", "created_at", "created_by"}
)


def _sanitize_data_keys(data: dict[str, Any]) -> None:
    for k, v in data.items():
        if (
            str(k).startswith("$")
            or "." in str(k)
            or str(k) in {"__proto__", "constructor", "prototype"}
        ):
            raise ValidationError(f"Disallowed key '{k}' in record data")
        if isinstance(v, dict):
            _sanitize_data_keys(v)


def _validate_against_collection_schema(schema_json: dict[str, Any], data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValidationError("Record data must be a JSON object")
    _sanitize_data_keys(data)
    if not schema_json:
        return
    try:
        Draft202012Validator(schema_json).validate(data)
    except JsonSchemaValidationError as exc:
        path = ".".join(str(p) for p in exc.absolute_path) or "data"
        raise ValidationError(
            f"Record failed schema validation: {exc.message}",
            details=[{"path": path, "reason": exc.message}],
        ) from exc


def _allowed_fields_for_collection(col: dict[str, Any]) -> set[str] | None:
    props = col.get("schema_json", {}).get("properties")
    searchable = set(col.get("searchable_fields") or [])
    if isinstance(props, dict) and props:
        return set(props.keys()) | searchable
    if searchable:
        return searchable
    return None


class RecordService:
    def __init__(
        self,
        *,
        settings: Settings,
        collections: CollectionService,
        records: RecordRepository,
        idempotency: IdempotencyRepository,
        audit: AuditService,
    ) -> None:
        self._settings = settings
        self._collections = collections
        self._records = records
        self._idempotency = idempotency
        self._audit = audit

    def create_record(
        self,
        actor: Actor,
        collection_id: str,
        data: dict[str, Any],
        *,
        source_type: str = "api",
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_WRITE
        )
        ws_id = col["workspace_id"]
        proj_id = col["project_id"]

        if idempotency_key:
            key_hash = hash_token(idempotency_key)
            digest = hashlib.sha256(
                json.dumps(data, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            existing = self._idempotency.get(f"{ws_id}:{collection_id}", "POST", "create", key_hash)
            if existing is not None:
                if existing["request_digest"] != digest:
                    raise ConflictError("Idempotency-Key reused with different payload")
                return dict(existing["response_body"]), True

        _validate_against_collection_schema(col.get("schema_json", {}), data)
        rec = self._records.insert_one(
            workspace_id=ws_id,
            project_id=proj_id,
            collection_id=collection_id,
            data=data,
            created_by=actor.principal_id,
            source={"type": source_type, "request_id": get_request_id()},
        )
        if idempotency_key:
            self._idempotency.save(
                scope=f"{ws_id}:{collection_id}",
                method="POST",
                path="create",
                key_hash=key_hash,
                request_digest=digest,
                status_code=201,
                response_body=rec,
            )
        self._audit.record(
            tenant=ws_id,
            actor_id=actor.principal_id,
            action="record.create",
            target=f"record:{rec['id']}",
            decision="allow",
        )
        return rec, False

    def batch_create(
        self,
        actor: Actor,
        collection_id: str,
        items: list[dict[str, Any]],
        *,
        source_type: str = "api",
    ) -> dict[str, Any]:
        if len(items) > self._settings.max_batch_records:
            raise PayloadTooLargeError(
                f"Batch exceeds max {self._settings.max_batch_records} records"
            )
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_WRITE
        )
        ws_id = col["workspace_id"]
        proj_id = col["project_id"]
        schema_json = col.get("schema_json", {})

        results: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        for idx, item in enumerate(items):
            try:
                _validate_against_collection_schema(schema_json, item)
                rec = self._records.insert_one(
                    workspace_id=ws_id,
                    project_id=proj_id,
                    collection_id=collection_id,
                    data=item,
                    created_by=actor.principal_id,
                    source={"type": source_type, "request_id": get_request_id()},
                )
                results.append(
                    {"index": idx, "status": "created", "id": rec["id"], "version": rec["version"]}
                )
                succeeded += 1
            except ValidationError as exc:
                results.append({"index": idx, "status": "error", "error": exc.message})
                failed += 1

        self._audit.record(
            tenant=ws_id,
            actor_id=actor.principal_id,
            action="record.batch_create",
            target=f"collection:{collection_id}",
            decision="allow",
            metadata={"succeeded": succeeded, "failed": failed},
        )
        return {"succeeded": succeeded, "failed": failed, "items": results}

    def get_record(self, actor: Actor, collection_id: str, record_id: str) -> dict[str, Any]:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_READ
        )
        rec = self._records.get_by_id(
            workspace_id=col["workspace_id"],
            project_id=col["project_id"],
            collection_id=collection_id,
            record_id=record_id,
        )
        if rec is None:
            raise NotFoundError("Record not found")
        return rec

    def update_record(
        self,
        actor: Actor,
        collection_id: str,
        record_id: str,
        patch: dict[str, Any],
        expected_version: int,
    ) -> dict[str, Any]:
        if any(k in _RESERVED_DATA_KEYS for k in patch):
            raise ValidationError("Cannot modify reserved metadata fields")
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_WRITE
        )
        ws_id = col["workspace_id"]
        proj_id = col["project_id"]

        current = self._records.get_by_id(
            workspace_id=ws_id,
            project_id=proj_id,
            collection_id=collection_id,
            record_id=record_id,
        )
        if current is None:
            raise NotFoundError("Record not found")

        merged = dict(current["data"])
        for k, v in patch.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v

        _validate_against_collection_schema(col.get("schema_json", {}), merged)
        updated = self._records.update_with_version(
            workspace_id=ws_id,
            project_id=proj_id,
            collection_id=collection_id,
            record_id=record_id,
            expected_version=expected_version,
            new_data=merged,
        )
        if updated is None:
            raise NotFoundError("Record not found")
        self._audit.record(
            tenant=ws_id,
            actor_id=actor.principal_id,
            action="record.update",
            target=f"record:{record_id}",
            decision="allow",
        )
        return updated

    def delete_record(
        self,
        actor: Actor,
        collection_id: str,
        record_id: str,
        expected_version: int,
    ) -> dict[str, Any]:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_DELETE
        )
        ws_id = col["workspace_id"]
        deleted = self._records.soft_delete_with_version(
            workspace_id=ws_id,
            project_id=col["project_id"],
            collection_id=collection_id,
            record_id=record_id,
            expected_version=expected_version,
        )
        if deleted is None:
            raise NotFoundError("Record not found")
        self._audit.record(
            tenant=ws_id,
            actor_id=actor.principal_id,
            action="record.delete",
            target=f"record:{record_id}",
            decision="allow",
        )
        return deleted

    def restore_record(self, actor: Actor, collection_id: str, record_id: str) -> dict[str, Any]:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_WRITE
        )
        ws_id = col["workspace_id"]
        restored = self._records.restore(
            workspace_id=ws_id,
            project_id=col["project_id"],
            collection_id=collection_id,
            record_id=record_id,
        )
        if restored is None:
            raise NotFoundError("Deleted record not found")
        self._audit.record(
            tenant=ws_id,
            actor_id=actor.principal_id,
            action="record.restore",
            target=f"record:{record_id}",
            decision="allow",
        )
        return restored

    def search_records(
        self,
        actor: Actor,
        collection_id: str,
        *,
        filter_ast: dict[str, Any] | None = None,
        sort: list[dict[str, str]] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_READ
        )
        ws_id = col["workspace_id"]
        proj_id = col["project_id"]
        allowed = _allowed_fields_for_collection(col)

        page_size = min(
            limit or self._settings.default_query_page_size,
            self._settings.structured_search_max_page_size,
            self._settings.max_query_page_size,
        )
        if page_size < 1:
            raise ValidationError("limit must be >= 1")

        sort_field_public = "created_at"
        sort_dir_str = "desc"
        if sort:
            first_sort = sort[0]
            sf = first_sort.get("field", "created_at")
            sd = first_sort.get("direction", "desc").lower()
            if sd not in {"asc", "desc"}:
                raise ValidationError("sort direction must be 'asc' or 'desc'")
            validate_field_name(sf, allowed)
            sort_field_public = sf
            sort_dir_str = sd

        mongo_sort_field = (
            "_id"
            if sort_field_public == "id"
            else (
                sort_field_public
                if sort_field_public in {"created_at", "updated_at", "version"}
                else f"data.{sort_field_public}"
            )
        )
        sort_dir = 1 if sort_dir_str == "asc" else -1

        mongo_filter = compile_filter(filter_ast, allowed_fields=allowed)
        plan = plan_search(
            actor,
            col,
            filter_ast,
            sort,
            fields,
            settings=self._settings,
        )
        if plan.mode == "rejected":
            raise QueryNotIndexedError(
                plan.refusal_reason or "Query is not backed by an approved source index"
            )
        projection = compile_projection(fields, allowed_fields=allowed)
        sig = query_signature(ws_id, collection_id, filter_ast, mongo_sort_field, sort_dir_str)

        cursor_filter = None
        if cursor:
            cursor_filter = decode_cursor(
                cursor=cursor,
                secret=self._settings.jwt_secret_key,
                expected_sig=sig,
                sort_field=mongo_sort_field,
                sort_direction=sort_dir,
            )

        rows = self._records.find_page(
            workspace_id=ws_id,
            project_id=proj_id,
            collection_id=collection_id,
            mongo_filter=mongo_filter,
            sort_field=mongo_sort_field,
            sort_direction=sort_dir,
            limit=page_size + 1,
            cursor_filter=cursor_filter,
            projection=projection,
            max_time_ms=min(
                self._settings.max_query_time_ms,
                self._settings.structured_search_max_time_ms,
            ),
        )

        has_more = len(rows) > page_size
        page_rows = rows[:page_size]
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            if sort_field_public == "id":
                sort_val: Any = last["id"]
            elif sort_field_public in {"created_at", "updated_at"}:
                # serialize_doc turned the BSON Date into an ISO string; restore the
                # datetime so the keyset cursor compares Date-to-Date in MongoDB.
                sort_val = parse_iso_datetime(last.get(sort_field_public))
            elif sort_field_public == "version":
                sort_val = last.get(sort_field_public)
            else:
                sort_val = last.get("data", {}).get(sort_field_public)
            next_cursor = encode_cursor(
                secret=self._settings.jwt_secret_key,
                sig=sig,
                sort_value=sort_val,
                last_id=last["id"],
            )

        return {
            "items": page_rows,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "limit": page_size,
        }

    def count_records(
        self,
        actor: Actor,
        collection_id: str,
        *,
        filter_ast: dict[str, Any] | None = None,
    ) -> int:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_READ
        )
        allowed = _allowed_fields_for_collection(col)
        mongo_filter = compile_filter(filter_ast, allowed_fields=allowed)
        return self._records.count(
            workspace_id=col["workspace_id"],
            project_id=col["project_id"],
            collection_id=collection_id,
            mongo_filter=mongo_filter,
            max_time_ms=self._settings.max_query_time_ms,
        )
