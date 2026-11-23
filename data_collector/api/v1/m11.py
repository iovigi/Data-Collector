"""API v1 endpoints for M11: saved queries, webhooks, schema migrations, usage analytics."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.domain.exceptions import BadRequestError

m11_bp = Blueprint("m11_v1", __name__)


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    return body


@m11_bp.post("/collections/<cid>/saved-queries")
@require_auth(is_mutation=True)
def create_saved_query(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    body = _json_body()
    res = get_container().saved_queries.create(
        actor,
        cid,
        name=str(body.get("name", "")),
        filter_ast=body.get("filter"),
        sort=body.get("sort"),
        fields=body.get("fields"),
        limit=int(body.get("limit", 25)),
    )
    return jsonify(res), 201


@m11_bp.get("/collections/<cid>/saved-queries")
@require_auth(is_mutation=False)
def list_saved_queries(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    return jsonify({"items": get_container().saved_queries.list_for_collection(actor, cid)}), 200


@m11_bp.post("/saved-queries/<sqid>/run")
@require_auth(is_mutation=False)
def run_saved_query(sqid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    cursor = request.args.get("cursor")
    return jsonify(get_container().saved_queries.run(actor, sqid, cursor=cursor)), 200


@m11_bp.post("/workspaces/<wid>/webhooks")
@require_auth(is_mutation=True)
def create_webhook(wid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    body = _json_body()
    res = get_container().webhooks.create(
        actor,
        wid,
        name=str(body.get("name", "")),
        url=str(body.get("url", "")),
        events=list(body.get("events", [])),
    )
    return jsonify(res), 201


@m11_bp.get("/workspaces/<wid>/webhooks")
@require_auth(is_mutation=False)
def list_webhooks(wid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    return jsonify({"items": get_container().webhooks.list_for_workspace(actor, wid)}), 200


@m11_bp.post("/collections/<cid>/schema-migrations/preview")
@require_auth(is_mutation=False)
def preview_schema_migration(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    body = _json_body()
    schema = body.get("schema_json")
    if not isinstance(schema, dict):
        raise BadRequestError("schema_json object is required")
    return jsonify(get_container().schema_migrations.preview(actor, cid, schema)), 200


@m11_bp.post("/collections/<cid>/schema-migrations/apply")
@require_auth(is_mutation=True)
def apply_schema_migration(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    body = _json_body()
    schema = body.get("schema_json")
    if not isinstance(schema, dict):
        raise BadRequestError("schema_json object is required")
    return jsonify(get_container().schema_migrations.apply(actor, cid, schema)), 200


@m11_bp.get("/workspaces/<wid>/usage")
@require_auth(is_mutation=False)
def workspace_usage(wid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    return jsonify(get_container().usage_analytics.summary(actor, wid)), 200
