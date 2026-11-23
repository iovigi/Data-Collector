"""Hardening tests: OAuth 2.1 PKCE, concurrent MCP isolation, >10k export, OpenAPI 3.1, M11."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import fakeredis
import httpx
import mongomock
import pytest
from data_collector.app import create_app
from data_collector.config import Settings
from data_collector.container import build_container
from data_collector.domain.exceptions import ValidationError
from data_collector.domain.identities import Actor, PrincipalType
from data_collector.infrastructure.ssrf import validate_outbound_url
from data_collector.mcp.auth import get_mcp_actor, reset_mcp_actor, set_mcp_actor
from data_collector.mcp.server_http import create_mcp_http_app
from starlette.testclient import TestClient


@pytest.fixture
def full_ctx(tmp_path):
    settings = Settings(
        app_env="test",
        jwt_secret_key="hardening-test-jwt-secret-key-32-bytes!!",
        allowed_origins=["https://chatgpt.com", "https://claude.ai"],
        mcp_public_url="https://collector.example.com/mcp",
        auth_issuer="https://collector.example.com",
        oauth_mode="builtin",
        storage_dir=str(tmp_path / "artifacts"),
    )
    mongo_client = mongomock.MongoClient()
    redis_client = fakeredis.FakeRedis()
    app = create_app(
        settings, mongo_client=mongo_client, redis_client=redis_client, ensure_indexes=True
    )
    app.config["TESTING"] = True
    container = app.extensions["container"]
    mcp_http_app = create_mcp_http_app(settings, container=container)
    yield app, container, mcp_http_app, settings, mongo_client, redis_client
    container.close()


def test_oauth_21_pkce_full_flow_and_revocation(full_ctx):
    _, container, mcp_http_app, settings, _, _ = full_ctx
    container.auth_service.register_user("oauth.user@example.com", "StrongPassword123!")
    client = TestClient(mcp_http_app)

    # 1. Discovery metadata matches live endpoints
    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm["resource"] == settings.mcp_public_url
    asm = client.get("/.well-known/oauth-authorization-server").json()
    assert asm["token_endpoint"].endswith("/oauth/token")
    assert client.get("/.well-known/jwks.json").json()["keys"][0]["alg"] == "RS256"

    # 2. Dynamic Client Registration
    reg = client.post(
        "/oauth/register",
        json={
            "client_name": "ChatGPT Test",
            "redirect_uris": ["https://chatgpt.com/aip/oauth/callback"],
        },
    )
    assert reg.status_code == 201
    client_id = reg.json()["client_id"]

    # 3. PKCE S256 Authorization Code grant (GET consent + CSRF -> POST approve)
    verifier = "v" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    auth_params = {
        "client_id": client_id,
        "redirect_uri": "https://chatgpt.com/aip/oauth/callback",
        "state": "st123",
        "scope": "workspace:read collection:read records:read",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": settings.mcp_public_url,
    }
    assert client.get("/oauth/authorize", params=auth_params).status_code == 200
    csrf_tok = client.cookies.get("dc_oauth_csrf")
    auth_resp = client.post(
        "/oauth/authorize",
        data={
            **auth_params,
            "csrf_token": csrf_tok,
            "consent": "approve",
            "email": "oauth.user@example.com",
            "password": "StrongPassword123!",
        },
        follow_redirects=False,
    )
    assert auth_resp.status_code == 302
    loc = urlparse(auth_resp.headers["location"])
    code = parse_qs(loc.query)["code"][0]

    # Wrong verifier fails
    bad_tok = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": "https://chatgpt.com/aip/oauth/callback",
            "code_verifier": "w" * 64,
        },
    )
    assert bad_tok.status_code == 400

    # New code + valid verifier succeeds
    assert client.get("/oauth/authorize", params=auth_params).status_code == 200
    csrf_tok2 = client.cookies.get("dc_oauth_csrf")
    auth_resp2 = client.post(
        "/oauth/authorize",
        data={
            **auth_params,
            "csrf_token": csrf_tok2,
            "consent": "approve",
            "email": "oauth.user@example.com",
            "password": "StrongPassword123!",
        },
        follow_redirects=False,
    )
    code2 = parse_qs(urlparse(auth_resp2.headers["location"]).query)["code"][0]
    tok_resp = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code2,
            "client_id": client_id,
            "redirect_uri": "https://chatgpt.com/aip/oauth/callback",
            "code_verifier": verifier,
        },
    )
    assert tok_resp.status_code == 200
    access_token = tok_resp.json()["access_token"]

    # Verified actor has OAUTH_CLIENT type & scoped permissions
    actor = container.oauth_service.verify_bearer_token(access_token)
    assert actor.principal_type == PrincipalType.OAUTH_CLIENT
    assert actor.client_id == client_id

    # Revoke token -> subsequent verification fails
    client.post("/oauth/revoke", data={"token": access_token, "client_id": client_id})
    with pytest.raises(Exception, match="revoked"):
        container.oauth_service.verify_bearer_token(access_token)


async def test_concurrent_mcp_actor_context_isolation():
    a1 = Actor(principal_id="user_a", principal_type=PrincipalType.OAUTH_CLIENT)
    a2 = Actor(principal_id="user_b", principal_type=PrincipalType.OAUTH_CLIENT)

    async def task_fn(actor: Actor, delay: float) -> str:
        tok = set_mcp_actor(actor)
        try:
            await asyncio.sleep(delay)
            return get_mcp_actor().principal_id
        finally:
            reset_mcp_actor(tok)

    r1, r2 = await asyncio.gather(task_fn(a1, 0.02), task_fn(a2, 0.01))
    assert r1 == "user_a"
    assert r2 == "user_b"


def test_api_key_collection_allowlist_and_ssrf_defense(full_ctx):
    app, container, _, _, _, _ = full_ctx
    u = container.auth_service.register_user("col.owner@example.com", "StrongPassword123!")
    owner = Actor(principal_id=u["id"], principal_type=PrincipalType.USER)
    ws = container.collection_service.create_workspace(owner, slug="ws-col", name="WS")
    proj = container.collection_service.create_project(
        owner, ws["id"], slug="proj-col", name="Proj"
    )
    c1 = container.collection_service.create_collection(
        owner, proj["id"], slug="col-one", schema_json={"type": "object"}
    )
    c2 = container.collection_service.create_collection(
        owner, proj["id"], slug="col-two", schema_json={"type": "object"}
    )

    key_res = container.auth_service.create_api_key(
        owner,
        workspace_id=ws["id"],
        name="col1-only",
        scopes=["collection:read", "records:read"],
        allowed_collection_ids=[c1["id"]],
    )
    key_actor = container.auth_service.authenticate_api_key(key_res["api_key"])
    visible = container.collection_service.list_collections(key_actor, proj["id"])
    assert [c["id"] for c in visible] == [c1["id"]]
    assert container.collection_service.get_collection(key_actor, c1["id"])["id"] == c1["id"]
    with pytest.raises(Exception, match="not permitted"):
        container.collection_service.get_collection(key_actor, c2["id"])

    # SSRF defense
    for bad_url in [
        "http://127.0.0.1/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.1/internal",
        "https://192.168.1.10/admin",
    ]:
        with pytest.raises(ValidationError):
            validate_outbound_url(bad_url)


def test_streaming_export_over_10k_and_restart_recovery(full_ctx):
    app, container, _, settings, mongo_client, redis_client = full_ctx
    u = container.auth_service.register_user("exp.user@example.com", "StrongPassword123!")
    owner = Actor(principal_id=u["id"], principal_type=PrincipalType.USER)
    ws = container.collection_service.create_workspace(owner, slug="ws-exp", name="Exp")
    proj = container.collection_service.create_project(
        owner, ws["id"], slug="proj-exp", name="Proj"
    )
    col = container.collection_service.create_collection(
        owner, proj["id"], slug="big-col", schema_json={"type": "object"}
    )

    # Bulk insert 10,500 records directly via collection to test >10,000 export
    docs = [
        {
            "workspace_id": ws["id"],
            "project_id": proj["id"],
            "collection_id": col["id"],
            "data": {"idx": i},
            "version": 1,
            "created_by": u["id"],
            "deleted_at": None,
        }
        for i in range(10500)
    ]
    container.mongo.db.records.insert_many(docs)

    job = container.export_service.submit_export(owner, col["id"], fmt="jsonl")
    assert job["state"] == "completed"
    assert job["progress"]["total"] == 10500
    assert job["output_ref"]["complete"] is True

    # Simulate app/worker restart with fresh Container against same DB & ArtifactStore
    restarted = build_container(settings, mongo_client=mongo_client, redis_client=redis_client)
    path, fmt, sha256 = restarted.export_service.get_export_result(owner, job["id"])
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 10500
    assert fmt == "jsonl"
    assert len(sha256) == 64


def test_openapi_31_and_m11_features(full_ctx):
    app, container, _, _, _, _ = full_ctx
    container.auth_service.register_user("m11@example.com", "StrongPassword123!")
    with app.test_client() as client:
        # OpenAPI 3.1 contract check
        spec = client.get("/api/v1/openapi.json").get_json()
        assert spec["openapi"] == "3.1.0"
        assert "BearerAuth" in spec["components"]["securitySchemes"]
        assert "ErrorEnvelope" in spec["components"]["schemas"]
        assert "CreateRecordRequest" in spec["components"]["schemas"]

        tok = client.post(
            "/api/v1/auth/login",
            json={"email": "m11@example.com", "password": "StrongPassword123!"},
        ).get_json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        wid = client.post(
            "/api/v1/workspaces", json={"slug": "m11-ws", "name": "M11"}, headers=h
        ).get_json()["id"]
        pid = client.post(
            f"/api/v1/workspaces/{wid}/projects", json={"slug": "m11-proj", "name": "P"}, headers=h
        ).get_json()["id"]
        cid = client.post(
            f"/api/v1/projects/{pid}/collections",
            json={
                "slug": "items",
                "schema_json": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}},
                },
                "searchable_fields": ["name"],
            },
            headers=h,
        ).get_json()["id"]

        client.post(
            f"/api/v1/collections/{cid}/records", json={"data": {"name": "alpha"}}, headers=h
        )

        # 1. Saved Queries
        sq = client.post(
            f"/api/v1/collections/{cid}/saved-queries",
            json={"name": "find-alpha", "filter": {"field": "name", "op": "eq", "value": "alpha"}},
            headers=h,
        )
        assert sq.status_code == 201
        sqid = sq.get_json()["id"]
        run_sq = client.post(f"/api/v1/saved-queries/{sqid}/run", headers=h)
        assert run_sq.status_code == 200
        assert len(run_sq.get_json()["items"]) == 1

        # 2. Webhooks (SSRF blocked + valid create & signed dispatch)
        bad_wh = client.post(
            f"/api/v1/workspaces/{wid}/webhooks",
            json={
                "name": "bad",
                "url": "https://169.254.169.254/hook",
                "events": ["record.created"],
            },
            headers=h,
        )
        assert bad_wh.status_code == 422

        wh = client.post(
            f"/api/v1/workspaces/{wid}/webhooks",
            json={
                "name": "good",
                "url": "https://127.0.0.1:9999/hook" if False else "http://localhost:9999/hook",
                "events": ["record.created"],
            },
            headers=h,
        )
        assert wh.status_code == 201
        assert "signing_secret" in wh.get_json()
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.post.return_value = MagicMock(status_code=200)
        deliveries = container.webhooks.dispatch_event(
            wid, "record.created", {"id": "1"}, http_client=mock_http
        )
        assert len(deliveries) == 1
        assert deliveries[0]["status"] == "delivered"

        # 3. Schema Migration Assistant
        incompat = client.post(
            f"/api/v1/collections/{cid}/schema-migrations/preview",
            json={
                "schema_json": {
                    "type": "object",
                    "required": ["name", "email"],
                    "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
                }
            },
            headers=h,
        )
        assert incompat.status_code == 200
        assert incompat.get_json()["compatible"] is False

        compat = client.post(
            f"/api/v1/collections/{cid}/schema-migrations/apply",
            json={
                "schema_json": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
                }
            },
            headers=h,
        )
        assert compat.status_code == 200
        assert compat.get_json()["schema_version"] == 2

        # 4. Usage Analytics
        usage = client.get(f"/api/v1/workspaces/{wid}/usage", headers=h)
        assert usage.status_code == 200
        assert usage.get_json()["records_active"] == 1
        assert usage.get_json()["collections"] == 1
