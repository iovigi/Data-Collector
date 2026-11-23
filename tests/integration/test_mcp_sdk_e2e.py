"""Real MCP SDK ClientSession E2E over live HTTP Streamable HTTP + concurrent isolation."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import fakeredis
import httpx
import mongomock
import pytest
import uvicorn
from data_collector.config import Settings
from data_collector.container import build_container
from data_collector.domain.identities import Actor, PrincipalType
from data_collector.mcp.server_http import create_mcp_http_app
from mcp.client.streamable_http import streamable_http_client

from mcp import ClientSession


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def live_mcp_http():
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    settings = Settings(
        app_env="test",
        jwt_secret_key="mcp-e2e-jwt-secret-key-32-bytes-minimum!",
        allowed_origins=["http://127.0.0.1", "http://localhost"],
        mcp_public_url=f"{base_url}/mcp",
        auth_issuer=base_url,
        oauth_mode="builtin",
        mcp_allow_writes=False,
    )
    ctr = build_container(
        settings,
        mongo_client=mongomock.MongoClient(),
        redis_client=fakeredis.FakeRedis(),
        ensure_indexes=True,
    )
    u_alice = ctr.auth_service.register_user("alice.e2e@example.com", "StrongPassword123!")
    u_bob = ctr.auth_service.register_user("bob.e2e@example.com", "StrongPassword123!")

    a_alice = Actor(principal_id=u_alice["id"], principal_type=PrincipalType.USER)
    ws_a = ctr.collection_service.create_workspace(a_alice, slug="alice-ws", name="Alice WS")
    proj_a = ctr.collection_service.create_project(a_alice, ws_a["id"], slug="alice-p", name="AP")
    col_a = ctr.collection_service.create_collection(
        a_alice,
        proj_a["id"],
        slug="alice-col",
        schema_json={"type": "object", "properties": {"secret_note": {"type": "string"}}},
        searchable_fields=["secret_note"],
    )
    ctr.record_service.create_record(a_alice, col_a["id"], {"secret_note": "ALICE_ONLY"})

    a_bob = Actor(principal_id=u_bob["id"], principal_type=PrincipalType.USER)
    ws_b = ctr.collection_service.create_workspace(a_bob, slug="bob-ws", name="Bob WS")

    tok_a = ctr.oauth_service._mint_oauth_tokens(
        user_id=u_alice["id"],
        email=u_alice["email"],
        client_id="e2e-client",
        scopes=["workspace:read", "collection:read", "records:read"],
        resource=settings.mcp_public_url,
        family_id="fa",
    )["access_token"]
    tok_b = ctr.oauth_service._mint_oauth_tokens(
        user_id=u_bob["id"],
        email=u_bob["email"],
        client_id="e2e-client",
        scopes=["workspace:read", "collection:read", "records:read"],
        resource=settings.mcp_public_url,
        family_id="fb",
    )["access_token"]

    app = create_mcp_http_app(settings, container=ctr)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server socket
    for _ in range(50):
        try:
            r = httpx.get(f"{base_url}/health/live", timeout=0.5)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.05)

    yield base_url, tok_a, tok_b, ws_a["id"], ws_b["id"], col_a["id"]
    server.should_exit = True
    thread.join(timeout=3)
    ctr.close()


async def _run_client_session(
    mcp_url: str, token: str, col_id_to_probe: str
) -> tuple[list[str], dict]:
    async with (
        httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, timeout=10.0
        ) as http_client,
        streamable_http_client(mcp_url, http_client=http_client) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools_res = await session.list_tools()
        tool_names = [t.name for t in tools_res.tools]
        assert "dc_list_workspaces" in tool_names

        ws_call = await session.call_tool("dc_list_workspaces", {})
        ws_payload = json.loads(ws_call.content[0].text)

        probe_call = await session.call_tool(
            "dc_search_records", {"collection_id": col_id_to_probe}
        )
        probe_payload = json.loads(probe_call.content[0].text)
        return ws_payload["items"], probe_payload


async def test_real_mcp_sdk_http_concurrent_clients(live_mcp_http):
    base_url, tok_a, tok_b, ws_a_id, ws_b_id, col_a_id = live_mcp_http
    mcp_url = f"{base_url}/mcp"

    res_a, res_b = await asyncio.gather(
        _run_client_session(mcp_url, tok_a, col_a_id),
        _run_client_session(mcp_url, tok_b, col_a_id),
    )

    ws_items_a, probe_a = res_a
    ws_items_b, probe_b = res_b

    assert [w["id"] for w in ws_items_a] == [ws_a_id]
    assert [w["id"] for w in ws_items_b] == [ws_b_id]

    assert probe_a["ok"] is True
    assert probe_a["items"][0]["data"]["secret_note"] == "ALICE_ONLY"

    # Bob cannot read Alice's collection even under concurrent requests
    assert probe_b["ok"] is False
    assert probe_b["error"]["code"] == "NOT_FOUND"
