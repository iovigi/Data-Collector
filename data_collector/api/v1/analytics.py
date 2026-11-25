"""Read-only collection analytics (same engine as the MCP aggregation tools)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.api.schemas import AggregateRequest, DistinctValuesRequest, HistogramRequest
from data_collector.domain.exceptions import BadRequestError

analytics_bp = Blueprint("analytics_v1", __name__)


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    return body


@analytics_bp.post("/collections/<cid>/analytics/aggregate")
@require_auth(is_mutation=False)
def aggregate(cid: str) -> ResponseReturnValue:
    dto = AggregateRequest.model_validate(_json_body())
    res = get_container().analytics.aggregate(
        get_current_actor(),
        cid,
        group_by=dto.group_by,
        metrics=dto.metrics,
        filter_ast=dto.filter,
        having=dto.having,
        sort=dto.sort,
        limit=dto.limit,
    )
    return jsonify(res), 200


@analytics_bp.post("/collections/<cid>/analytics/distinct")
@require_auth(is_mutation=False)
def distinct_values(cid: str) -> ResponseReturnValue:
    dto = DistinctValuesRequest.model_validate(_json_body())
    res = get_container().analytics.distinct_values(
        get_current_actor(), cid, field=dto.field, filter_ast=dto.filter, limit=dto.limit
    )
    return jsonify(res), 200


@analytics_bp.post("/collections/<cid>/analytics/histogram")
@require_auth(is_mutation=False)
def histogram(cid: str) -> ResponseReturnValue:
    dto = HistogramRequest.model_validate(_json_body())
    res = get_container().analytics.histogram(
        get_current_actor(),
        cid,
        date_field=dto.date_field,
        interval=dto.interval,
        filter_ast=dto.filter,
    )
    return jsonify(res), 200


@analytics_bp.get("/collections/<cid>/analytics/fields")
@require_auth(is_mutation=False)
def fields(cid: str) -> ResponseReturnValue:
    return jsonify(get_container().analytics.describe_fields(get_current_actor(), cid)), 200
