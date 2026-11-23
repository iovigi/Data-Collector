"""MCP over the in-process WSGI bridge used by IIS (stateless JSON Streamable HTTP).

A plain threaded WSGI server stands in for IIS FastCGI: it calls the exact composed WSGI
callable IIS will call. The real MCP SDK client connects over HTTP.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading

import fakeredis
import httpx
import mongomock
import pytest
from data_collector.app import create_app
from data_collector.config import Settings
from data_collector.domain.identities import Actor, PrincipalType
from data_collector.hosting.mcp_bridge import PathDispatcher, build_mcp_wsgi, is_mcp_path
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from werkzeug.serving import make_server

SCOPES = ["workspace:read", "collection:read", "records:read"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def wsgi_mcp():
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    settings = Settings(
        app_env="test",
        jwt_secret_key="mcp-wsgi-jwt-secret-key-32-bytes-minimum!",
        allowed_origins=[base],
        mcp_public_url=f"{base}/mcp",
        auth_issuer=base,
        oauth_mode="builtin",
    )
    app = create_app(
        settings,
        mongo_client=mongomock.MongoClient(),
        redis_client=fakeredis.FakeRedis(),
        ensure_indexes=True,
    )
    ctr = app.extensions["container"]
    u_a = ctr.auth_service.register_user("alice.wsgi@example.com", "StrongPassword123!")
    u_b = ctr.auth_service.register_user("bob.wsgi@example.com", "StrongPassword123!")
    a = Actor(principal_id=u_a["id"], principal_type=PrincipalType.USER)
    b = Actor(principal_id=u_b["id"], principal_type=PrincipalType.USER)
    ws_a = ctr.collection_service.create_workspace(a, slug="alice-ws", name="Alice")
    proj = ctr.collection_service.create_project(a, ws_a["id"], slug="alice-p", name="P")
    col = ctr.collection_service.create_collection(
        a,
        proj["id"],
        slug="alice-col",
        schema_json={"type": "object", "properties": {"note": {"type": "string"}}},
        searchable_fields=["note"],
    )
    ctr.record_service.create_record(a, col["id"], {"note": "ALICE_ONLY"})
    ws_b = ctr.collection_service.create_workspace(b, slug="bob-ws", name="Bob")

    def mint(user: dict, fam: str) -> str:
        return ctr.oauth_service._mint_oauth_tokens(
            user_id=user["id"],
            email=user["email"],
            client_id="wsgi-client",
            scopes=SCOPES,
            resource=settings.mcp_public_url,
            family_id=fam,
        )["access_token"]

    composed = PathDispatcher(app.wsgi_app, build_mcp_wsgi(settings, ctr))
    server = make_server("127.0.0.1", port, composed, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {
        "base": base,
        "tok_a": mint(u_a, "fa"),
        "tok_b": mint(u_b, "fb"),
        "ws_a": ws_a["id"],
        "ws_b": ws_b["id"],
        "col_a": col["id"],
    }
    server.shutdown()
    thread.join(timeout=5)


async def _session(url: str, token: str, probe_col: str) -> tuple[list[str], dict, dict]:
    async with (
        httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=15) as http,
        streamable_http_client(url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        assert init.serverInfo.name == "data-collector"
        tools = [t.name for t in (await session.list_tools()).tools]
        ws = json.loads((await session.call_tool("dc_list_workspaces", {})).content[0].text)
        probe = json.loads(
            (await session.call_tool("dc_search_records", {"collection_id": probe_col}))
            .content[0]
            .text
        )
        return tools, ws, probe


def test_real_sdk_clients_concurrent_isolation(wsgi_mcp):
    url = wsgi_mcp["base"] + "/mcp"

    async def both():
        return await asyncio.gather(
            _session(url, wsgi_mcp["tok_a"], wsgi_mcp["col_a"]),
            _session(url, wsgi_mcp["tok_b"], wsgi_mcp["col_a"]),
        )

    (tools_a, ws_a, probe_a), (tools_b, ws_b, probe_b) = asyncio.run(both())
    for tools in (tools_a, tools_b):
        assert {"dc_list_workspaces", "dc_search_records"} <= set(tools)
    assert [w["id"] for w in ws_a["items"]] == [wsgi_mcp["ws_a"]]
    assert [w["id"] for w in ws_b["items"]] == [wsgi_mcp["ws_b"]]
    assert probe_a["ok"] is True
    assert "ALICE_ONLY" in json.dumps(probe_a)
    assert probe_b["ok"] is False
    assert "ALICE_ONLY" not in json.dumps(probe_b)


def test_transport_semantics(wsgi_mcp):
    base = wsgi_mcp["base"]
    init_msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "1"},
        },
    }
    accept = {"Accept": "application/json, text/event-stream"}

    r = httpx.post(f"{base}/mcp", json=init_msg, headers=accept)
    assert r.status_code == 401
    assert 'resource_metadata="' in r.headers["WWW-Authenticate"]
    assert "<html" not in r.text.lower()

    auth = {**accept, "Authorization": f"Bearer {wsgi_mcp['tok_a']}"}
    r = httpx.post(f"{base}/mcp", json=init_msg, headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["result"]["serverInfo"]["name"] == "data-collector"

    for method in ("GET", "DELETE"):
        r = httpx.request(method, f"{base}/mcp", headers=auth, timeout=10)
        assert r.status_code == 405
        assert r.headers["Allow"] == "POST"

    forged = {**auth, "Host": "evil.example"}
    assert httpx.post(f"{base}/mcp", json=init_msg, headers=forged).status_code == 421

    prm = httpx.get(f"{base}/.well-known/oauth-protected-resource").json()
    assert prm["resource"] == f"{base}/mcp"
    asm = httpx.get(f"{base}/.well-known/oauth-authorization-server").json()
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert "keys" in httpx.get(f"{base}/.well-known/jwks.json").json()

    # Flask side of the same process still serves the REST API
    assert httpx.get(f"{base}/api/v1/openapi.json").status_code == 200
    assert httpx.get(f"{base}/health/ready").status_code == 200


def test_path_routing():
    assert is_mcp_path("/mcp")
    assert is_mcp_path("/.well-known/oauth-protected-resource")
    assert is_mcp_path("/oauth/token")
    assert not is_mcp_path("/mcpx")
    assert not is_mcp_path("/api/v1/me")
    assert not is_mcp_path("/w/abc/mcp")
