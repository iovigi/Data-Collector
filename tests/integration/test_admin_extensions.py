"""Integration tests for S1 Admin Dashboard backend API extensions."""

from __future__ import annotations

import fakeredis
import mongomock
import pytest
from data_collector.app import create_app
from data_collector.config import Settings


@pytest.fixture
def s1_ctx():
    settings = Settings(
        app_env="test",
        jwt_secret_key="s1-admin-ext-jwt-secret-key-32-bytes!!",
        allowed_origins=["http://localhost:3000"],
    )
    app = create_app(
        settings,
        mongo_client=mongomock.MongoClient(),
        redis_client=fakeredis.FakeRedis(),
        ensure_indexes=True,
    )
    app.config["TESTING"] = True
    ctr = app.extensions["container"]
    u_owner = ctr.auth_service.register_user("owner.s1@example.com", "StrongPassword123!")
    u_colleague = ctr.auth_service.register_user("colleague.s1@example.com", "StrongPassword123!")
    ctr.auth_service.register_user("outsider.s1@example.com", "StrongPassword123!")

    with app.test_client() as client:
        tok_owner = client.post(
            "/api/v1/auth/login",
            json={"email": "owner.s1@example.com", "password": "StrongPassword123!"},
        ).get_json()["access_token"]
        tok_colleague = client.post(
            "/api/v1/auth/login",
            json={"email": "colleague.s1@example.com", "password": "StrongPassword123!"},
        ).get_json()["access_token"]
        tok_outsider = client.post(
            "/api/v1/auth/login",
            json={"email": "outsider.s1@example.com", "password": "StrongPassword123!"},
        ).get_json()["access_token"]
        yield (
            client,
            {"Authorization": f"Bearer {tok_owner}"},
            {"Authorization": f"Bearer {tok_colleague}"},
            {"Authorization": f"Bearer {tok_outsider}"},
            u_owner["id"],
            u_colleague["id"],
        )
    ctr.close()


def test_capabilities_members_invitations_and_last_owner_protection(s1_ctx):
    client, h_owner, h_colleague, h_outsider, owner_id, colleague_id = s1_ctx

    wid = client.post(
        "/api/v1/workspaces", json={"slug": "s1-ws", "name": "S1 WS"}, headers=h_owner
    ).get_json()["id"]

    # Capabilities for owner
    cap = client.get(f"/api/v1/workspaces/{wid}/capabilities", headers=h_owner)
    assert cap.status_code == 200
    assert cap.get_json()["role"] == "owner"
    assert cap.get_json()["features"]["can_create_keys"] is True

    # Invite colleague by email
    inv = client.post(
        f"/api/v1/workspaces/{wid}/invitations",
        json={"email": "colleague.s1@example.com", "role": "viewer"},
        headers=h_owner,
    )
    assert inv.status_code == 201
    inv_id = inv.get_json()["id"]
    inv_token = inv.get_json()["invite_token"]

    # Outsider cannot accept colleague's invitation
    bad_acc = client.post(
        f"/api/v1/invitations/{inv_id}/accept",
        json={"token": inv_token},
        headers=h_outsider,
    )
    assert bad_acc.status_code == 403

    # Colleague accepts invitation
    acc = client.post(
        f"/api/v1/invitations/{inv_id}/accept",
        json={"token": inv_token},
        headers=h_colleague,
    )
    assert acc.status_code == 200
    assert acc.get_json()["role"] == "viewer"

    # Capabilities for viewer colleague
    cap_v = client.get(f"/api/v1/workspaces/{wid}/capabilities", headers=h_colleague).get_json()
    assert cap_v["role"] == "viewer"
    assert cap_v["features"]["can_write_records"] is False
    assert cap_v["features"]["can_create_keys"] is False

    # Cannot remove or demote last owner
    assert (
        client.delete(f"/api/v1/workspaces/{wid}/members/{owner_id}", headers=h_owner).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v1/workspaces/{wid}/members/{owner_id}",
            json={"role": "admin"},
            headers=h_owner,
        ).status_code
        == 409
    )

    # Upgrade colleague to editor, then transfer ownership (old owner becomes admin)
    assert (
        client.patch(
            f"/api/v1/workspaces/{wid}/members/{colleague_id}",
            json={"role": "editor"},
            headers=h_owner,
        ).status_code
        == 200
    )
    members = client.get(f"/api/v1/workspaces/{wid}/members", headers=h_owner).get_json()["items"]
    assert len(members) == 2

    xfer = client.post(
        f"/api/v1/workspaces/{wid}/transfer-ownership",
        json={"target_principal_id": colleague_id},
        headers=h_owner,
    )
    assert xfer.status_code == 200
    assert (
        client.get(f"/api/v1/workspaces/{wid}/capabilities", headers=h_colleague).get_json()["role"]
        == "owner"
    )


def test_lifecycle_trash_jobs_audit_saved_queries_webhooks_and_summary(s1_ctx):
    client, h_owner, _, h_outsider, _, _ = s1_ctx
    wid = client.post(
        "/api/v1/workspaces", json={"slug": "life-ws", "name": "Life WS"}, headers=h_owner
    ).get_json()["id"]
    assert (
        client.patch(
            f"/api/v1/workspaces/{wid}", json={"name": "Life Renamed"}, headers=h_owner
        ).status_code
        == 200
    )

    pid = client.post(
        f"/api/v1/workspaces/{wid}/projects",
        json={"slug": "proj-life", "name": "Proj"},
        headers=h_owner,
    ).get_json()["id"]
    assert client.get(f"/api/v1/projects/{pid}", headers=h_owner).status_code == 200
    assert client.get(f"/api/v1/projects/{pid}", headers=h_outsider).status_code == 404
    assert (
        client.patch(
            f"/api/v1/projects/{pid}", json={"name": "Proj 2"}, headers=h_owner
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/projects/{pid}/archive", headers=h_owner).status_code == 200
    assert client.post(f"/api/v1/projects/{pid}/restore", headers=h_owner).status_code == 200

    cid = client.post(
        f"/api/v1/projects/{pid}/collections",
        json={
            "slug": "trash-col",
            "schema_json": {"type": "object", "properties": {"name": {"type": "string"}}},
            "searchable_fields": ["name"],
        },
        headers=h_owner,
    ).get_json()["id"]

    rid = client.post(
        f"/api/v1/collections/{cid}/records",
        json={"data": {"name": "rec1"}},
        headers=h_owner,
    ).get_json()["id"]
    assert (
        client.delete(
            f"/api/v1/collections/{cid}/records/{rid}",
            json={"expected_version": 1},
            headers=h_owner,
        ).status_code
        == 200
    )

    trash = client.get(f"/api/v1/collections/{cid}/records/trash", headers=h_owner)
    assert trash.status_code == 200
    assert len(trash.get_json()["items"]) == 1

    # Saved query CRUD
    sqid = client.post(
        f"/api/v1/collections/{cid}/saved-queries",
        json={"name": "q1"},
        headers=h_owner,
    ).get_json()["id"]
    assert client.get(f"/api/v1/saved-queries/{sqid}", headers=h_owner).status_code == 200
    assert (
        client.patch(
            f"/api/v1/saved-queries/{sqid}", json={"name": "q1-renamed"}, headers=h_owner
        ).status_code
        == 200
    )
    assert client.delete(f"/api/v1/saved-queries/{sqid}", headers=h_owner).status_code == 200

    # Webhook CRUD + rotate-secret + deliveries
    hid = client.post(
        f"/api/v1/workspaces/{wid}/webhooks",
        json={"name": "wh1", "url": "http://localhost:9999/hook", "events": ["record.created"]},
        headers=h_owner,
    ).get_json()["id"]
    assert (
        client.get(f"/api/v1/workspaces/{wid}/webhooks/{hid}", headers=h_owner).status_code == 200
    )
    assert (
        client.patch(
            f"/api/v1/workspaces/{wid}/webhooks/{hid}",
            json={"status": "disabled"},
            headers=h_owner,
        ).status_code
        == 200
    )
    rot = client.post(f"/api/v1/workspaces/{wid}/webhooks/{hid}/rotate-secret", headers=h_owner)
    assert rot.status_code == 200
    assert "signing_secret" in rot.get_json()
    assert (
        client.get(
            f"/api/v1/workspaces/{wid}/webhooks/{hid}/deliveries", headers=h_owner
        ).status_code
        == 200
    )
    assert (
        client.delete(f"/api/v1/workspaces/{wid}/webhooks/{hid}", headers=h_owner).status_code
        == 200
    )

    # Paginated jobs, paginated audit & dashboard summary
    assert client.get(f"/api/v1/workspaces/{wid}/jobs", headers=h_owner).status_code == 200
    aud = client.get(f"/api/v1/workspaces/{wid}/audit?limit=5", headers=h_owner)
    assert aud.status_code == 200
    assert len(aud.get_json()["items"]) == 5

    summary = client.get(f"/api/v1/workspaces/{wid}/dashboard/summary", headers=h_owner)
    assert summary.status_code == 200
    assert summary.get_json()["counts"]["projects"] == 1
