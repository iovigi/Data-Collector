"""Integration tests for Data API v1 (auth, tenancy, CRUD, search, idempotency, keys)."""

from __future__ import annotations

import fakeredis
import mongomock
import pytest
from data_collector.app import create_app
from data_collector.config import Settings


@pytest.fixture
def api_ctx():
    settings = Settings(
        app_env="test",
        jwt_secret_key="integration-test-jwt-secret-key-32-bytes!",
        allowed_origins=["http://localhost:3000"],
    )
    mongo_client = mongomock.MongoClient()
    redis_client = fakeredis.FakeRedis()
    app = create_app(
        settings, mongo_client=mongo_client, redis_client=redis_client, ensure_indexes=True
    )
    app.config["TESTING"] = True
    container = app.extensions["container"]
    with app.test_client() as client:
        yield client, container
    container.close()


def _login(client, container, email: str, password: str) -> dict[str, str]:
    container.auth_service.register_user(email, password)
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    return resp.get_json()


def test_health_and_openapi(api_ctx):
    client, _ = api_ctx
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    spec = client.get("/api/v1/openapi.json").get_json()
    assert spec["openapi"] == "3.1.0"
    assert "/api/v1/collections/{cid}/records" in spec["paths"]


def test_auth_login_uniform_failure_and_refresh_replay(api_ctx):
    client, container = api_ctx
    tokens = _login(client, container, "alice@example.com", "StrongPassword123!")

    # Non-existent user vs wrong password return identical 401
    r1 = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x"})
    r2 = client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong"})
    assert r1.status_code == 401
    assert r2.status_code == 401
    assert r1.get_json()["error"]["message"] == r2.get_json()["error"]["message"]

    # Refresh rotates token
    ref1 = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert ref1.status_code == 200
    new_tokens = ref1.get_json()

    # Replaying old refresh token revokes family
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    after_replay = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert after_replay.status_code == 401


def test_full_tenant_isolation_crud_search_idempotency_and_keys(api_ctx):
    client, container = api_ctx
    alice = _login(client, container, "alice2@example.com", "StrongPassword123!")
    bob = _login(client, container, "bob@example.com", "StrongPassword123!")
    h_alice = {"Authorization": f"Bearer {alice['access_token']}"}
    h_bob = {"Authorization": f"Bearer {bob['access_token']}"}

    # Alice creates workspace -> project -> collection with JSON schema
    ws = client.post(
        "/api/v1/workspaces", json={"slug": "acme-ws", "name": "Acme"}, headers=h_alice
    )
    assert ws.status_code == 201
    wid = ws.get_json()["id"]

    proj = client.post(
        f"/api/v1/workspaces/{wid}/projects",
        json={"slug": "crm", "name": "CRM"},
        headers=h_alice,
    )
    assert proj.status_code == 201
    pid = proj.get_json()["id"]

    schema = {
        "type": "object",
        "required": ["name", "status"],
        "properties": {
            "name": {"type": "string"},
            "status": {"type": "string"},
            "score": {"type": "integer"},
        },
        "additionalProperties": False,
    }
    col = client.post(
        f"/api/v1/projects/{pid}/collections",
        json={
            "slug": "leads",
            "schema_json": schema,
            "searchable_fields": ["name", "status", "score"],
        },
        headers=h_alice,
    )
    assert col.status_code == 201
    cid = col.get_json()["id"]

    # Bob cannot access Alice's workspace or collection (404, no existence leak)
    assert client.get(f"/api/v1/workspaces/{wid}", headers=h_bob).status_code == 404
    assert client.get(f"/api/v1/collections/{cid}", headers=h_bob).status_code == 404
    assert client.get(f"/api/v1/collections/{cid}/records", headers=h_bob).status_code == 404

    # Schema validation rejects invalid record
    bad_rec = client.post(
        f"/api/v1/collections/{cid}/records",
        json={"data": {"name": "Lead 1", "extra": 1}},
        headers=h_alice,
    )
    assert bad_rec.status_code == 422

    # Idempotent create
    h_idem = {**h_alice, "Idempotency-Key": "idem-001"}
    r_create1 = client.post(
        f"/api/v1/collections/{cid}/records",
        json={"data": {"name": "Lead 1", "status": "active", "score": 50}},
        headers=h_idem,
    )
    assert r_create1.status_code == 201
    rid = r_create1.get_json()["id"]

    r_create2 = client.post(
        f"/api/v1/collections/{cid}/records",
        json={"data": {"name": "Lead 1", "status": "active", "score": 50}},
        headers=h_idem,
    )
    assert r_create2.status_code == 200
    assert r_create2.get_json()["id"] == rid

    r_conflict = client.post(
        f"/api/v1/collections/{cid}/records",
        json={"data": {"name": "Lead 2", "status": "active", "score": 10}},
        headers=h_idem,
    )
    assert r_conflict.status_code == 409

    # Optimistic concurrency update
    r_upd_conflict = client.patch(
        f"/api/v1/collections/{cid}/records/{rid}",
        json={"patch": {"score": 99}, "expected_version": 99},
        headers=h_alice,
    )
    assert r_upd_conflict.status_code == 409

    r_upd_ok = client.patch(
        f"/api/v1/collections/{cid}/records/{rid}",
        json={"patch": {"score": 99}, "expected_version": 1},
        headers=h_alice,
    )
    assert r_upd_ok.status_code == 200
    assert r_upd_ok.get_json()["version"] == 2

    # Search with Safe Query DSL
    r_search = client.post(
        f"/api/v1/collections/{cid}/records/search",
        json={
            "filter": {"field": "score", "op": "gte", "value": 90},
            "fields": ["name", "score"],
            "limit": 10,
        },
        headers=h_alice,
    )
    assert r_search.status_code == 200
    assert len(r_search.get_json()["items"]) == 1

    # Soft delete + restore
    r_del = client.delete(
        f"/api/v1/collections/{cid}/records/{rid}",
        json={"expected_version": 2},
        headers=h_alice,
    )
    assert r_del.status_code == 200
    assert (
        client.get(f"/api/v1/collections/{cid}/records/{rid}", headers=h_alice).status_code == 404
    )

    r_rest = client.post(
        f"/api/v1/collections/{cid}/records/{rid}/restore",
        headers=h_alice,
    )
    assert r_rest.status_code == 200
    assert r_rest.get_json()["version"] == 4

    # Scoped API key creation & immediate revocation
    k_resp = client.post(
        "/api/v1/keys",
        json={"workspace_id": wid, "name": "reader", "scopes": ["collection:read", "records:read"]},
        headers=h_alice,
    )
    assert k_resp.status_code == 201
    raw_key = k_resp.get_json()["api_key"]
    kid = k_resp.get_json()["id"]

    assert (
        client.get(f"/api/v1/collections/{cid}/records", headers={"X-API-Key": raw_key}).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/collections/{cid}/records",
            json={"data": {"name": "x", "status": "new"}},
            headers={"X-API-Key": raw_key},
        ).status_code
        == 403
    )

    assert (
        client.post(
            f"/api/v1/keys/{kid}/revoke", json={"workspace_id": wid}, headers=h_alice
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/collections/{cid}/records", headers={"X-API-Key": raw_key}).status_code
        == 401
    )

    # Audit events recorded
    aud = client.get(f"/api/v1/audit?workspace_id={wid}", headers=h_alice)
    assert aud.status_code == 200
    assert len(aud.get_json()["items"]) >= 3
