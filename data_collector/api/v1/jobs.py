"""Import, export, and job status endpoints."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request, send_file
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.domain.exceptions import BadRequestError

jobs_bp = Blueprint("jobs_v1", __name__)


@jobs_bp.post("/collections/<cid>/imports")
@require_auth(is_mutation=True)
def create_import(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    fmt = request.args.get("format", "json")
    dry_run = request.args.get("dry_run", "false").lower() == "true"
    raw = request.get_data()
    if not raw:
        raise BadRequestError("Import payload body is required")
    idem = request.headers.get("Idempotency-Key")
    job = get_container().import_service.submit_import(
        actor, cid, raw_bytes=raw, fmt=fmt, dry_run=dry_run, idempotency_key=idem
    )
    return jsonify(job), 202


@jobs_bp.post("/collections/<cid>/exports")
@require_auth(is_mutation=False)
def create_export(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    body = request.get_json(silent=True) or {}
    fmt = str(body.get("format", "jsonl"))
    filter_ast = body.get("filter")
    job = get_container().export_service.submit_export(actor, cid, fmt=fmt, filter_ast=filter_ast)
    return jsonify(job), 202


@jobs_bp.get("/jobs/<jid>")
@require_auth(is_mutation=False)
def get_job(jid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    job = get_container().import_service.get_job(actor, jid)
    return jsonify(job), 200


@jobs_bp.get("/jobs/<jid>/result")
@require_auth(is_mutation=False)
def get_job_result(jid: str) -> Response:
    actor = get_current_actor()
    path, fmt, sha256 = get_container().export_service.get_export_result(actor, jid)
    mime = {"json": "application/json", "jsonl": "application/x-ndjson", "csv": "text/csv"}.get(
        fmt, "application/octet-stream"
    )
    resp = send_file(path, mimetype=mime, as_attachment=True, download_name=f"export-{jid}.{fmt}")
    resp.headers["X-Content-SHA256"] = sha256
    return resp


@jobs_bp.post("/jobs/<jid>/cancel")
@require_auth(is_mutation=True)
def cancel_job(jid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    job = get_container().import_service.cancel_job(actor, jid)
    return jsonify(job), 200
