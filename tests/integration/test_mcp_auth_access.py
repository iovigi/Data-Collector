"""MCP auth: personal access tokens, two-step consent bound to a workspace, connected-client
grants, REST/MCP credential separation, audit attribution, and the connection check."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
import socket
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import fakeredis
import httpx
import mongomock
import pytest
import uvicorn
from data_collector.app import create_app
from data_collector.config import Settings
from data_collector.domain.exceptions import ValidationError
from data_collector.infrastructure.oauth import redirect_uri_matches, validate_redirect_uri
from data_collector.mcp.server_http import create_mcp_http_app
from mcp.client.streamable_http import streamable_http_client

from mcp import ClientSession

PW = "StrongPassword123!"
CLAUDE_REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def env():
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    settings = Settings(
        app_env="test",
        jwt_secret_key="mcp-auth-access-jwt-secret-key-32-bytes!",
        allowed_origins=["http://127.0.0.1"],
        mcp_public_url=f"{base}/mcp",
        auth_issuer=base,
        oauth_mode="builtin",
        rate_limit_write_per_minute=10_000,
        rate_limit_read_per_minute=10_000,
    )
    flask_app = create_app(
        settings,
        mongo_client=mongomock.MongoClient(),
        redis_client=fakeredis.FakeRedis(),
        ensure_indexes=True,
    )
    ctr = flask_app.extensions["container"]
    mcp_app = create_mcp_http_app(settings, container=ctr)
    server = uvicorn.Server(uvicorn.Config(mcp_app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            if httpx.get(f"{base}/health/live", timeout=0.5).status_code == 200:
                break
        except Exception:
            time.sleep(0.05)

    rest = flask_app.test_client()
    h: dict[str, dict[str, str]] = {}
    users: dict[str, dict[str, Any]] = {}
    for name in ("owner", "viewer"):
        users[name] = ctr.auth_service.register_user(f"{name}.mcpa@example.com", PW)
        tok = rest.post(
            "/api/v1/auth/login", json={"email": f"{name}.mcpa@example.com", "password": PW}
        ).get_json()["access_token"]
        h[name] = {"Authorization": f"Bearer {tok}"}
    wid = rest.post(
        "/api/v1/workspaces", json={"slug": "mcpa-main", "name": "Main"}, headers=h["owner"]
    ).get_json()["id"]
    wid2 = rest.post(
        "/api/v1/workspaces", json={"slug": "mcpa-other", "name": "Other"}, headers=h["owner"]
    ).get_json()["id"]
    rest.post(
        f"/api/v1/workspaces/{wid}/members",
        json={"principal_id": users["viewer"]["id"], "role": "viewer"},
        headers=h["owner"],
    )
    pid = rest.post(
        f"/api/v1/workspaces/{wid}/projects", json={"slug": "proj", "name": "P"}, headers=h["owner"]
    ).get_json()["id"]
    cid = rest.post(
        f"/api/v1/projects/{pid}/collections",
        json={"slug": "leads", "json_schema": {"type": "object", "properties": {"x": {}}}},
        headers=h["owner"],
    ).get_json()["id"]
    yield {
        "base": base,
        "mcp": f"{base}/mcp",
        "rest": rest,
        "ctr": ctr,
        "h": h,
        "users": users,
        "wid": wid,
        "wid2": wid2,
        "cid": cid,
        "settings": settings,
    }
    server.should_exit = True
    thread.join(timeout=3)
    ctr.close()


async def _mcp(url: str, headers: dict[str, str], calls: list[tuple[str, dict]]) -> dict:
    async with (
        httpx.AsyncClient(headers=headers, timeout=15.0) as http,
        streamable_http_client(url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        out: dict[str, Any] = {"tools": [t.name for t in (await session.list_tools()).tools]}
        for name, args in calls:
            res = await session.call_tool(name, args)
            out[name] = json.loads(res.content[0].text)
        return out


def _raw_mcp_status(url: str, headers: dict[str, str]) -> tuple[int, str]:
    r = httpx.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={**headers, "Accept": "application/json, text/event-stream"},
        timeout=10,
    )
    return r.status_code, r.text


# ── personal access tokens ────────────────────────────────────────────────────
def test_pat_lifecycle_and_credential_separation(env):
    rest, h, wid, cid = env["rest"], env["h"], env["wid"], env["cid"]
    created = rest.post(
        f"/api/v1/workspaces/{wid}/mcp/tokens", json={"name": "Claude Code"}, headers=h["owner"]
    )
    assert created.status_code == 201, created.get_json()
    body = created.get_json()
    pat = body["token"]
    assert pat.startswith("dcp_") and body["read_only"] is True
    assert body["scopes"] == ["workspace:read", "collection:read", "records:read"]
    assert "key_hash" not in body

    # Shown once: the list never contains the secret; PATs are not in the API-key list.
    listed = rest.get(f"/api/v1/workspaces/{wid}/mcp/tokens", headers=h["owner"]).get_json()
    assert [t["prefix"] for t in listed["items"]] == [body["prefix"]]
    assert pat not in json.dumps(listed)
    keys = rest.get(f"/api/v1/keys?workspace_id={wid}", headers=h["owner"]).get_json()
    assert all(k["prefix"] != body["prefix"] for k in keys.get("items", keys))

    # Works on /mcp as a Bearer token and is bound to its one workspace.
    out = asyncio.run(
        _mcp(
            env["mcp"],
            {"Authorization": f"Bearer {pat}"},
            [
                ("dc_list_workspaces", {}),
                ("dc_aggregate", {"collection_id": cid}),
                ("dc_create_record", {"collection_id": cid, "data": {"x": 1}}),
            ],
        )
    )
    assert "dc_aggregate" in out["tools"]
    assert [w["id"] for w in out["dc_list_workspaces"]["items"]] == [wid]
    assert out["dc_aggregate"]["ok"] is True
    assert out["dc_create_record"]["ok"] is False  # read-only token, writes disabled

    # Refused on every REST surface.
    assert rest.get(f"/api/v1/workspaces/{wid}", headers={"X-API-Key": pat}).status_code == 401
    assert (
        rest.get(
            f"/api/v1/workspaces/{wid}", headers={"Authorization": f"Bearer {pat}"}
        ).status_code
        == 401
    )
    assert (
        rest.get(f"/api/v1/collections/{cid}/records", headers={"X-API-Key": pat}).status_code
        == 401
    )

    # Revoked: /mcp rejects it.
    tid = body["id"]
    assert (
        rest.post(
            f"/api/v1/workspaces/{wid}/mcp/tokens/{tid}/revoke", headers=h["owner"]
        ).status_code
        == 200
    )
    status, text = _raw_mcp_status(env["mcp"], {"Authorization": f"Bearer {pat}"})
    assert status == 401 and "revoked" in text


def test_pat_scopes_capped_by_role_and_needs_a_session(env):
    rest, h, wid = env["rest"], env["h"], env["wid"]
    r = rest.post(
        f"/api/v1/workspaces/{wid}/mcp/tokens",
        json={"name": "w", "scopes": ["records:read", "records:write"]},
        headers=h["viewer"],
    )
    assert r.status_code == 403
    r = rest.post(
        f"/api/v1/workspaces/{wid}/mcp/tokens",
        json={"name": "w", "scopes": ["keys:manage"]},
        headers=h["owner"],
    )
    assert r.status_code == 422
    # Viewer can mint a read-only token for themselves; cannot revoke the owner's.
    own = rest.post(
        f"/api/v1/workspaces/{wid}/mcp/tokens", json={"name": "mine"}, headers=h["owner"]
    ).get_json()
    assert (
        rest.post(
            f"/api/v1/workspaces/{wid}/mcp/tokens", json={"name": "v"}, headers=h["viewer"]
        ).status_code
        == 201
    )
    viewer_list = rest.get(f"/api/v1/workspaces/{wid}/mcp/tokens", headers=h["viewer"]).get_json()
    assert [t["name"] for t in viewer_list["items"]] == ["v"]
    assert (
        rest.post(
            f"/api/v1/workspaces/{wid}/mcp/tokens/{own['id']}/revoke", headers=h["viewer"]
        ).status_code
        == 403
    )
    # A key cannot mint MCP tokens.
    key = rest.post(
        "/api/v1/keys",
        json={"workspace_id": wid, "name": "k", "scopes": ["workspace:read", "records:read"]},
        headers=h["owner"],
    ).get_json()["api_key"]
    assert (
        rest.post(
            f"/api/v1/workspaces/{wid}/mcp/tokens", json={"name": "x"}, headers={"X-API-Key": key}
        ).status_code
        == 403
    )
    # A workspace API key sent as Bearer on /mcp gets a precise message, not "audience".
    status, text = _raw_mcp_status(env["mcp"], {"Authorization": f"Bearer {key}"})
    assert status == 401 and "not MCP tokens" in text


def test_oauth_mcp_token_cannot_call_rest(env):
    ctr = env["ctr"]
    tok = ctr.oauth_service._mint_oauth_tokens(
        user_id=env["users"]["owner"]["id"],
        email="owner.mcpa@example.com",
        client_id="c",
        scopes=["workspace:read", "records:read"],
        resource=env["settings"].mcp_public_url,
        family_id="fam-rest",
    )["access_token"]
    for path in (f"/api/v1/workspaces/{env['wid']}", f"/api/v1/workspaces/{env['wid']}/members"):
        assert env["rest"].get(path, headers={"Authorization": f"Bearer {tok}"}).status_code == 401


# ── OAuth: redirect rules and two-step consent ────────────────────────────────
def test_redirect_uri_rules():
    assert validate_redirect_uri("http://localhost:33418/callback", allow_localhost_dev=False)
    assert validate_redirect_uri("http://127.0.0.1:5000/cb", allow_localhost_dev=False)
    with pytest.raises(ValidationError):
        validate_redirect_uri("http://evil.example/cb", allow_localhost_dev=False)
    assert redirect_uri_matches("http://localhost:1111/callback", "http://localhost:2222/callback")
    assert not redirect_uri_matches("http://localhost:1/callback", "http://localhost:1/other")
    assert not redirect_uri_matches("https://claude.ai/a", "https://claude.ai.evil/a")
    assert not redirect_uri_matches("http://localhost:1/cb", "http://127.0.0.1:1/cb")


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _csrf(page: str) -> str:
    m = re.search(r"name='csrf_token' value='([^']+)'", page)
    assert m, page[:400]
    return m.group(1)


def _consent_flow(env, *, approve_writes: bool = False) -> dict[str, Any]:
    """claude.ai-shaped flow: DCR without scope, all advertised scopes requested,
    resource with trailing slash, plus an unknown scope."""
    c = httpx.Client(base_url=env["base"], timeout=15, follow_redirects=False)
    reg = c.post(
        "/oauth/register", json={"client_name": "Claude", "redirect_uris": [CLAUDE_REDIRECT]}
    )
    assert reg.status_code == 201
    client_id = reg.json()["client_id"]
    prm = c.get("/.well-known/oauth-protected-resource/mcp").json()
    verifier, challenge = _pkce()
    q = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CLAUDE_REDIRECT,
        "scope": " ".join(prm["scopes_supported"]) + " offline_access",
        "state": "st-1",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": env["mcp"] + "/",
    }
    page = c.get("/oauth/authorize", params=q)
    assert page.status_code == 200, page.text
    assert "Claude" in page.text and "Read records and run counts" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    hidden = dict(re.findall(r"name='([a-z_]+)' value='([^']*)'", page.text))

    bad = c.post(
        "/oauth/authorize",
        data={
            **hidden,
            "email": "owner.mcpa@example.com",
            "password": "wrong",
            "consent": "continue",
        },
    )
    assert bad.status_code == 401 and "Invalid" in bad.text
    hidden = dict(re.findall(r"name='([a-z_]+)' value='([^']*)'", bad.text))

    consent = c.post(
        "/oauth/authorize",
        data={**hidden, "email": "owner.mcpa@example.com", "password": PW, "consent": "continue"},
    )
    assert consent.status_code == 200, consent.text
    assert "Allow access?" in consent.text
    assert "Main (mcpa-main)" in consent.text and "Other (mcpa-other)" in consent.text
    assert "Read-only" in consent.text  # MCP_ALLOW_WRITES is off in this env
    ticket = re.search(r"name='ticket' value='([^']+)'", consent.text).group(1)  # type: ignore[union-attr]
    data = {
        "csrf_token": _csrf(consent.text),
        "step": "consent",
        "ticket": ticket,
        "workspace_id": env["wid"],
        "consent": "approve",
    }
    if approve_writes:
        data["allow_writes"] = "on"
    done = c.post("/oauth/authorize", data=data)
    assert done.status_code == 302, done.text
    qs = parse_qs(urlparse(done.headers["location"]).query)
    assert qs["state"] == ["st-1"]
    tok = c.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": qs["code"][0],
            "client_id": client_id,
            "redirect_uri": CLAUDE_REDIRECT,
            "code_verifier": verifier,
        },
    )
    assert tok.status_code == 200, tok.text
    return {**tok.json(), "client_id": client_id, "http": c}


def test_two_step_consent_binds_workspace_and_is_read_only(env):
    t = _consent_flow(env, approve_writes=True)
    # Writes were ticked but the server has MCP_ALLOW_WRITES off: read scopes only.
    assert set(t["scope"].split()) == {
        "workspace:read",
        "collection:read",
        "records:read",
        "jobs:read",
        "export:read",
    }
    out = asyncio.run(
        _mcp(
            env["mcp"],
            {"Authorization": f"Bearer {t['access_token']}"},
            [("dc_list_workspaces", {}), ("dc_list_projects", {"workspace_id": env["wid2"]})],
        )
    )
    assert [w["id"] for w in out["dc_list_workspaces"]["items"]] == [env["wid"]]
    assert out["dc_list_projects"]["ok"] is False  # other workspace of the same user


def test_grants_list_last_use_audit_and_revoke(env):
    rest, h, wid, ctr = env["rest"], env["h"], env["wid"], env["ctr"]
    t = _consent_flow(env)
    asyncio.run(
        _mcp(
            env["mcp"],
            {"Authorization": f"Bearer {t['access_token']}"},
            [("dc_aggregate", {"collection_id": env["cid"]})],
        )
    )
    grants = rest.get(f"/api/v1/workspaces/{wid}/mcp/grants", headers=h["owner"]).get_json()[
        "items"
    ]
    assert len(grants) == 1
    g = grants[0]
    assert g["client_name"] == "Claude" and g["email"] == "owner.mcpa@example.com"
    assert g["last_used_at"] is not None
    # Viewer sees none of the owner's connections and cannot revoke them.
    assert (
        rest.get(f"/api/v1/workspaces/{wid}/mcp/grants", headers=h["viewer"]).get_json()["items"]
        == []
    )
    assert (
        rest.post(
            f"/api/v1/workspaces/{wid}/mcp/grants/{g['id']}/revoke", headers=h["viewer"]
        ).status_code
        == 403
    )

    # Every MCP call is attributed to the user AND the OAuth client.
    ev = ctr.mongo.db.audit_events.find_one(
        {"action": "mcp.tool_call", "metadata.tool": "dc_aggregate"}
    )
    assert ev["actor"] == env["users"]["owner"]["id"]
    assert ev["tenant"] == wid
    assert ev["metadata"]["client_id"] == t["client_id"]
    assert ev["metadata"]["credential"] == "oauth"
    assert ctr.mongo.db.audit_events.count_documents({"action": "oauth.grant", "tenant": wid}) == 1

    assert (
        rest.post(
            f"/api/v1/workspaces/{wid}/mcp/grants/{g['id']}/revoke", headers=h["owner"]
        ).status_code
        == 200
    )
    status, text = _raw_mcp_status(env["mcp"], {"Authorization": f"Bearer {t['access_token']}"})
    assert status == 401 and "revoked" in text
    refresh = t["http"].post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": t["refresh_token"],
            "client_id": t["client_id"],
        },
    )
    assert refresh.status_code == 400
    assert (
        rest.get(f"/api/v1/workspaces/{wid}/mcp/grants", headers=h["owner"]).get_json()["items"]
        == []
    )


def test_refresh_keeps_workspace_binding(env):
    t = _consent_flow(env)
    r = t["http"].post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": t["refresh_token"],
            "client_id": t["client_id"],
        },
    )
    assert r.status_code == 200
    out = asyncio.run(
        _mcp(
            env["mcp"],
            {"Authorization": f"Bearer {r.json()['access_token']}"},
            [("dc_list_workspaces", {})],
        )
    )
    assert [w["id"] for w in out["dc_list_workspaces"]["items"]] == [env["wid"]]


def test_metadata_and_challenge(env):
    c = httpx.Client(base_url=env["base"], timeout=10)
    prm = c.get("/.well-known/oauth-protected-resource").json()
    assert prm["resource"] == env["mcp"]
    assert "keys:manage" not in prm["scopes_supported"]
    asm = c.get("/.well-known/oauth-authorization-server").json()
    assert asm["registration_endpoint"].endswith("/oauth/register")
    assert asm["code_challenge_methods_supported"] == ["S256"]
    status, _ = _raw_mcp_status(env["mcp"], {})
    assert status == 401
    r = c.post(env["mcp"], json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    challenge = r.headers["www-authenticate"]
    assert (
        "resource_metadata=" in challenge
        and 'scope="workspace:read collection:read records:read"' in challenge
    )


# ── admin connection info + outside-in check ──────────────────────────────────
def test_connection_info_and_check(env):
    rest, h, wid = env["rest"], env["h"], env["wid"]
    info = rest.get(f"/api/v1/workspaces/{wid}/mcp/connection-info", headers=h["viewer"]).get_json()
    assert info["mcp_url"] == env["mcp"]
    assert info["workspace"]["slug"] == "mcpa-main"
    assert "dc_aggregate" in info["tools"] and info["writes_enabled"] is False
    res = rest.post(f"/api/v1/workspaces/{wid}/mcp/connection-check", headers=h["owner"]).get_json()
    assert res["ok"] is True, res["checks"]
    assert [c["check"] for c in res["checks"]] == [
        "Protected resource metadata",
        "Authorization server metadata",
        "Token endpoint",
        "MCP endpoint asks for sign-in",
        "Tool listing",
    ]
    assert "dc_aggregate" in res["tools"]
    # Outsider workspace id: 404.
    assert (
        rest.get(
            f"/api/v1/workspaces/{'0' * 24}/mcp/connection-info", headers=h["owner"]
        ).status_code
        == 404
    )
