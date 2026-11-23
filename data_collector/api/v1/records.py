"""Record CRUD, search, batch, soft-delete, and restore endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.api.schemas import (
    BatchCreateRecordsRequest,
    CreateRecordRequest,
    DeleteRecordRequest,
    SearchRecordsRequest,
    UpdateRecordRequest,
)
from data_collector.domain.exceptions import BadRequestError

records_bp = Blueprint("records_v1", __name__)


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    return body


@records_bp.post("/collections/<cid>/records")
@require_auth(is_mutation=True)
def create_record(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    dto = CreateRecordRequest.model_validate(_json_body())
    idem = request.headers.get("Idempotency-Key")
    rec, replayed = get_container().record_service.create_record(
        actor, cid, dto.data, idempotency_key=idem
    )
    return jsonify(rec), (200 if replayed else 201)


@records_bp.post("/collections/<cid>/records/batch")
@require_auth(is_mutation=True)
def batch_create_records(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    dto = BatchCreateRecordsRequest.model_validate(_json_body())
    res = get_container().record_service.batch_create(actor, cid, dto.items)
    return jsonify(res), 207 if res["failed"] else 201


@records_bp.get("/collections/<cid>/records")
@require_auth(is_mutation=False)
def list_records(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    limit = int(request.args.get("limit", 25))
    cursor = request.args.get("cursor")
    res = get_container().record_service.search_records(actor, cid, limit=limit, cursor=cursor)
    return jsonify(res), 200


@records_bp.post("/collections/<cid>/records/search")
@require_auth(is_mutation=False)
def search_records(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    dto = SearchRecordsRequest.model_validate(_json_body())
    sort_list = [s.model_dump() for s in dto.sort] if dto.sort else None
    res = get_container().record_service.search_records(
        actor,
        cid,
        filter_ast=dto.filter,
        sort=sort_list,
        fields=dto.fields,
        limit=dto.limit,
        cursor=dto.cursor,
    )
    return jsonify(res), 200


@records_bp.get("/collections/<cid>/records/<rid>")
@require_auth(is_mutation=False)
def get_record(cid: str, rid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    rec = get_container().record_service.get_record(actor, cid, rid)
    return jsonify(rec), 200


@records_bp.patch("/collections/<cid>/records/<rid>")
@require_auth(is_mutation=True)
def update_record(cid: str, rid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    body = _json_body()
    if "If-Match" in request.headers and "expected_version" not in body:
        try:
            body["expected_version"] = int(request.headers["If-Match"].strip('"'))
        except ValueError as exc:
            raise BadRequestError("Invalid If-Match header") from exc
    dto = UpdateRecordRequest.model_validate(body)
    rec = get_container().record_service.update_record(
        actor, cid, rid, dto.patch, dto.expected_version
    )
    return jsonify(rec), 200


@records_bp.delete("/collections/<cid>/records/<rid>")
@require_auth(is_mutation=True)
def delete_record(cid: str, rid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    body = request.get_json(silent=True) or {}
    if "If-Match" in request.headers and "expected_version" not in body:
        try:
            body["expected_version"] = int(request.headers["If-Match"].strip('"'))
        except ValueError as exc:
            raise BadRequestError("Invalid If-Match header") from exc
    if "expected_version" not in body and request.args.get("expected_version"):
        try:
            body["expected_version"] = int(request.args["expected_version"])
        except ValueError as exc:
            raise BadRequestError("Invalid expected_version") from exc
    dto = DeleteRecordRequest.model_validate(body)
    rec = get_container().record_service.delete_record(actor, cid, rid, dto.expected_version)
    return jsonify(
        {"id": rec["id"], "version": rec["version"], "deleted_at": rec["deleted_at"]}
    ), 200


@records_bp.post("/collections/<cid>/records/<rid>/restore")
@require_auth(is_mutation=True)
def restore_record(cid: str, rid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    rec = get_container().record_service.restore_record(actor, cid, rid)
    return jsonify(rec), 200
