"""API v1 extensions for Admin Dashboard (S1)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.domain.exceptions import BadRequestError

admin_ext_bp = Blueprint("admin_ext_v1", __name__)


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    return body


@admin_ext_bp.get("/workspaces/<wid>/capabilities")
@require_auth(is_mutation=False)
def workspace_capabilities(wid: str) -> ResponseReturnValue:
    return jsonify(get_container().admin_ext.get_capabilities(get_current_actor(), wid)), 200


@admin_ext_bp.get("/workspaces/<wid>/dashboard/summary")
@require_auth(is_mutation=False)
def workspace_dashboard_summary(wid: str) -> ResponseReturnValue:
    return jsonify(get_container().admin_ext.dashboard_summary(get_current_actor(), wid)), 200


@admin_ext_bp.get("/workspaces/<wid>/members")
@require_auth(is_mutation=False)
def list_members(wid: str) -> ResponseReturnValue:
    limit = int(request.args.get("limit", 50))
    cursor = request.args.get("cursor")
    return jsonify(
        get_container().admin_ext.list_members(get_current_actor(), wid, limit=limit, cursor=cursor)
    ), 200


@admin_ext_bp.patch("/workspaces/<wid>/members/<pid>")
@require_auth(is_mutation=True)
def update_member_role(wid: str, pid: str) -> ResponseReturnValue:
    body = _json_body()
    res = get_container().admin_ext.update_member_role(
        get_current_actor(), wid, pid, str(body.get("role", ""))
    )
    return jsonify(res), 200


@admin_ext_bp.delete("/workspaces/<wid>/members/<pid>")
@require_auth(is_mutation=True)
def remove_member(wid: str, pid: str) -> ResponseReturnValue:
    get_container().admin_ext.remove_member(get_current_actor(), wid, pid)
    return jsonify({"status": "removed"}), 200


@admin_ext_bp.post("/workspaces/<wid>/transfer-ownership")
@require_auth(is_mutation=True)
def transfer_ownership(wid: str) -> ResponseReturnValue:
    body = _json_body()
    res = get_container().admin_ext.transfer_ownership(
        get_current_actor(), wid, str(body.get("target_principal_id", ""))
    )
    return jsonify(res), 200


@admin_ext_bp.post("/workspaces/<wid>/invitations")
@require_auth(is_mutation=True)
def create_invitation(wid: str) -> ResponseReturnValue:
    body = _json_body()
    res = get_container().admin_ext.create_invitation(
        get_current_actor(),
        wid,
        email=str(body.get("email", "")),
        role_name=str(body.get("role", "viewer")),
    )
    return jsonify(res), 201


@admin_ext_bp.get("/workspaces/<wid>/invitations")
@require_auth(is_mutation=False)
def list_invitations(wid: str) -> ResponseReturnValue:
    return jsonify(
        {"items": get_container().admin_ext.list_invitations(get_current_actor(), wid)}
    ), 200


@admin_ext_bp.post("/invitations/<iid>/accept")
@require_auth(is_mutation=True)
def accept_invitation(iid: str) -> ResponseReturnValue:
    body = _json_body()
    res = get_container().admin_ext.accept_invitation(
        get_current_actor(), iid, str(body.get("token", ""))
    )
    return jsonify(res), 200


@admin_ext_bp.post("/invitations/<iid>/revoke")
@require_auth(is_mutation=True)
def revoke_invitation(iid: str) -> ResponseReturnValue:
    return jsonify(get_container().admin_ext.revoke_invitation(get_current_actor(), iid)), 200


@admin_ext_bp.patch("/workspaces/<wid>")
@require_auth(is_mutation=True)
def update_workspace(wid: str) -> ResponseReturnValue:
    body = _json_body()
    return jsonify(
        get_container().admin_ext.update_workspace(
            get_current_actor(), wid, name=str(body.get("name", ""))
        )
    ), 200


@admin_ext_bp.post("/workspaces/<wid>/archive")
@require_auth(is_mutation=True)
def archive_workspace(wid: str) -> ResponseReturnValue:
    return jsonify(
        get_container().admin_ext.set_workspace_status(get_current_actor(), wid, "archived")
    ), 200


@admin_ext_bp.post("/workspaces/<wid>/restore")
@require_auth(is_mutation=True)
def restore_workspace(wid: str) -> ResponseReturnValue:
    return jsonify(
        get_container().admin_ext.set_workspace_status(get_current_actor(), wid, "active")
    ), 200


@admin_ext_bp.get("/projects/<pid>")
@require_auth(is_mutation=False)
def get_project(pid: str) -> ResponseReturnValue:
    return jsonify(get_container().admin_ext.get_project(get_current_actor(), pid)), 200


@admin_ext_bp.patch("/projects/<pid>")
@require_auth(is_mutation=True)
def update_project(pid: str) -> ResponseReturnValue:
    body = _json_body()
    return jsonify(
        get_container().admin_ext.update_project(get_current_actor(), pid, name=body.get("name"))
    ), 200


@admin_ext_bp.post("/projects/<pid>/archive")
@require_auth(is_mutation=True)
def archive_project(pid: str) -> ResponseReturnValue:
    return jsonify(
        get_container().admin_ext.update_project(get_current_actor(), pid, status="archived")
    ), 200


@admin_ext_bp.post("/projects/<pid>/restore")
@require_auth(is_mutation=True)
def restore_project(pid: str) -> ResponseReturnValue:
    return jsonify(
        get_container().admin_ext.update_project(get_current_actor(), pid, status="active")
    ), 200


@admin_ext_bp.get("/workspaces/<wid>/jobs")
@require_auth(is_mutation=False)
def list_workspace_jobs(wid: str) -> ResponseReturnValue:
    return jsonify(
        get_container().admin_ext.list_workspace_jobs(
            get_current_actor(),
            wid,
            state=request.args.get("state") or request.args.get("status"),
            job_type=request.args.get("type"),
            limit=int(request.args.get("limit", 50)),
            cursor=request.args.get("cursor"),
        )
    ), 200


@admin_ext_bp.get("/workspaces/<wid>/audit")
@require_auth(is_mutation=False)
def list_workspace_audit(wid: str) -> ResponseReturnValue:
    return jsonify(
        get_container().admin_ext.list_workspace_audit_paginated(
            get_current_actor(),
            wid,
            actor_id=request.args.get("actor_id"),
            action=request.args.get("action"),
            decision=request.args.get("decision"),
            limit=int(request.args.get("limit", 50)),
            cursor=request.args.get("cursor"),
        )
    ), 200


@admin_ext_bp.get("/collections/<cid>/records/trash")
@require_auth(is_mutation=False)
def list_record_trash(cid: str) -> ResponseReturnValue:
    return jsonify(
        get_container().admin_ext.list_record_trash(
            get_current_actor(),
            cid,
            limit=int(request.args.get("limit", 25)),
            cursor=request.args.get("cursor"),
        )
    ), 200


@admin_ext_bp.get("/saved-queries/<sqid>")
@require_auth(is_mutation=False)
def get_saved_query(sqid: str) -> ResponseReturnValue:
    return jsonify(get_container().admin_ext.get_saved_query(get_current_actor(), sqid)), 200


@admin_ext_bp.patch("/saved-queries/<sqid>")
@require_auth(is_mutation=True)
def update_saved_query(sqid: str) -> ResponseReturnValue:
    body = _json_body()
    return jsonify(
        get_container().admin_ext.update_saved_query(
            get_current_actor(),
            sqid,
            name=body.get("name"),
            filter_ast=body.get("filter"),
            sort=body.get("sort"),
            fields=body.get("fields"),
            limit=body.get("limit"),
        )
    ), 200


@admin_ext_bp.delete("/saved-queries/<sqid>")
@require_auth(is_mutation=True)
def delete_saved_query(sqid: str) -> ResponseReturnValue:
    get_container().admin_ext.delete_saved_query(get_current_actor(), sqid)
    return jsonify({"status": "deleted"}), 200


@admin_ext_bp.get("/workspaces/<wid>/webhooks/<hid>")
@require_auth(is_mutation=False)
def get_webhook(wid: str, hid: str) -> ResponseReturnValue:
    return jsonify(get_container().admin_ext.get_webhook(get_current_actor(), wid, hid)), 200


@admin_ext_bp.patch("/workspaces/<wid>/webhooks/<hid>")
@require_auth(is_mutation=True)
def update_webhook(wid: str, hid: str) -> ResponseReturnValue:
    body = _json_body()
    return jsonify(
        get_container().admin_ext.update_webhook(
            get_current_actor(),
            wid,
            hid,
            name=body.get("name"),
            url=body.get("url"),
            events=body.get("events"),
            status=body.get("status"),
        )
    ), 200


@admin_ext_bp.delete("/workspaces/<wid>/webhooks/<hid>")
@require_auth(is_mutation=True)
def delete_webhook(wid: str, hid: str) -> ResponseReturnValue:
    get_container().admin_ext.delete_webhook(get_current_actor(), wid, hid)
    return jsonify({"status": "deleted"}), 200


@admin_ext_bp.post("/workspaces/<wid>/webhooks/<hid>/rotate-secret")
@require_auth(is_mutation=True)
def rotate_webhook_secret(wid: str, hid: str) -> ResponseReturnValue:
    return jsonify(
        get_container().admin_ext.rotate_webhook_secret(get_current_actor(), wid, hid)
    ), 200


@admin_ext_bp.get("/workspaces/<wid>/webhooks/<hid>/deliveries")
@require_auth(is_mutation=False)
def list_webhook_deliveries(wid: str, hid: str) -> ResponseReturnValue:
    return jsonify(
        {
            "items": get_container().admin_ext.list_webhook_deliveries(
                get_current_actor(), wid, hid, limit=int(request.args.get("limit", 50))
            )
        }
    ), 200
