"""Tiered, million-record-safe collection count endpoints."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.api.schemas import BatchCollectionCountsRequest
from data_collector.domain.exceptions import BadRequestError

counts_bp = Blueprint("counts_v1", __name__)


def _parse_bool(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes"}


@counts_bp.get("/collections/<cid>/record-count")
@require_auth(is_mutation=False)
def get_collection_record_count(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    include_trash = _parse_bool(request.args.get("include_trash"))
    refresh = _parse_bool(request.args.get("refresh"))
    res = get_container().collection_counts.get_collection_count(
        actor, cid, include_trash=include_trash, refresh=refresh
    )
    return jsonify(res), 200


@counts_bp.post("/collections/counts")
@require_auth(is_mutation=False)
def batch_collection_record_counts() -> ResponseReturnValue:
    actor = get_current_actor()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    dto = BatchCollectionCountsRequest.model_validate(body)
    res = get_container().collection_counts.get_batch_counts(
        actor, dto.collection_ids, include_trash=dto.include_trash
    )
    return jsonify(res), 200


@counts_bp.post("/collections/<cid>/record-count/refresh")
@require_auth(is_mutation=False)
def refresh_collection_record_count(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    include_trash = _parse_bool(request.args.get("include_trash"))
    res, status_code = get_container().collection_counts.trigger_refresh(
        actor, cid, include_trash=include_trash
    )
    resp: Response = jsonify(res)
    if status_code in {429, 503}:
        resp.headers["Retry-After"] = "15"
    return resp, status_code
