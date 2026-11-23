"""MCP protocol, security, OAuth metadata, and two-stage delete tests (M7-M8)."""

from __future__ import annotations

import json

import fakeredis
import mongomock
import pytest
from data_collector.config import Settings
from data_collector.container import build_container
from data_collector.domain.identities import Actor, PrincipalType
from data_collector.mcp.auth import set_mcp_actor
from data_collector.mcp.contracts import cap_tool_response
from data_collector.mcp.server_http import create_mcp_http_app
from data_collector.mcp.tools import build_mcp_server
from starlette.testclient import TestClient


@pytest.fixture
def mcp_ctx():
    settings = Settings(
        app_env="test",
        jwt_secret_key="mcp-test-jwt-secret-key-at-least-32-bytes!",
        allowed_origins=["https://chatgpt.com", "https://claude.ai"],
        mcp_allow_writes=True,
    )
    container = build_container(
        settings,
        mongo_client=mongomock.MongoClient(),
        redis_client=fakeredis.FakeRedis(),
        ensure_indexes=True,
    )
    alice_user = container.auth_service.register_user("alice.mcp@example.com", "StrongPassword123!")
    bob_user = container.auth_service.register_user("bob.mcp@example.com", "StrongPassword123!")

    alice_owner = Actor(principal_id=alice_user["id"], principal_type=PrincipalType.USER)
    ws = container.collection_service.create_workspace(alice_owner, slug="mcp-ws", name="MCP WS")
    proj = container.collection_service.create_project(
        alice_owner, ws["id"], slug="mcp-proj", name="Proj"
    )
    col = container.collection_service.create_collection(
        alice_owner,
        proj["id"],
        slug="customers",
        schema_json={
            "type": "object",
            "required": ["name", "status"],
            "properties": {"name": {"type": "string"}, "status": {"type": "string"}},
        },
        searchable_fields=["name", "status"],
    )
    yield container, alice_user["id"], bob_user["id"], ws["id"], proj["id"], col["id"]
    set_mcp_actor(None)
    container.close()


def _parse_tool_result(res) -> dict:
    # FastMCP.call_tool returns (content_list, structured_dict) or list[TextContent]
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], dict):
        return res[1]
    if isinstance(res, list) and res:
        return json.loads(res[0].text)
    raise AssertionError(f"Unexpected tool result: {res!r}")


async def test_mcp_tool_discovery_and_read_only_enforcement(mcp_ctx):
    container, alice_id, bob_id, ws_id, proj_id, cid = mcp_ctx
    mcp = build_mcp_server(container)

    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert {
        "dc_list_workspaces",
        "dc_list_projects",
        "dc_list_collections",
        "dc_describe_collection",
        "dc_get_record",
        "dc_search_records",
        "dc_count_records",
        "dc_create_record",
        "dc_update_record",
        "dc_prepare_delete_record",
        "dc_delete_record",
        "dc_create_export_job",
        "dc_get_job",
    }.issubset(names)
    assert "run_mongodb_query" not in names
    assert "execute_python" not in names

    # Read-only MCP actor cannot write even if workspace owner
    ro_actor = Actor(
        principal_id=alice_id,
        principal_type=PrincipalType.OAUTH_CLIENT,
        is_mcp=True,
        mcp_allow_writes=False,
    )
    set_mcp_actor(ro_actor)
    res_ws = _parse_tool_result(await mcp.call_tool("dc_list_workspaces", {}))
    assert res_ws["ok"] is True
    assert len(res_ws["items"]) == 1

    res_denied = _parse_tool_result(
        await mcp.call_tool(
            "dc_create_record", {"collection_id": cid, "data": {"name": "A", "status": "new"}}
        )
    )
    assert res_denied["ok"] is False
    assert res_denied["error"]["code"] == "FORBIDDEN"


async def test_mcp_write_update_two_stage_delete_and_isolation(mcp_ctx):
    container, alice_id, bob_id, ws_id, proj_id, cid = mcp_ctx
    mcp = build_mcp_server(container)

    rw_alice = Actor(
        principal_id=alice_id,
        principal_type=PrincipalType.OAUTH_CLIENT,
        is_mcp=True,
        mcp_allow_writes=True,
    )
    set_mcp_actor(rw_alice)

    # Create
    c1 = _parse_tool_result(
        await mcp.call_tool(
            "dc_create_record",
            {
                "collection_id": cid,
                "data": {"name": "Acme Lead", "status": "active"},
                "idempotency_key": "m1",
            },
        )
    )
    assert c1["ok"] is True
    rid = c1["id"]

    # Search & count
    s1 = _parse_tool_result(
        await mcp.call_tool(
            "dc_search_records",
            {"collection_id": cid, "filter": {"field": "status", "op": "eq", "value": "active"}},
        )
    )
    assert s1["ok"] is True
    assert len(s1["items"]) == 1

    cnt = _parse_tool_result(await mcp.call_tool("dc_count_records", {"collection_id": cid}))
    assert cnt["count"] == 1

    # Delete without valid confirmation token fails
    bad_del = _parse_tool_result(
        await mcp.call_tool(
            "dc_delete_record",
            {
                "collection_id": cid,
                "record_id": rid,
                "expected_version": 1,
                "confirmation_token": "fake.sig",
            },
        )
    )
    assert bad_del["ok"] is False
    assert bad_del["error"]["code"] == "FORBIDDEN"

    # Two-stage delete: prepare -> delete -> replay rejected
    prep = _parse_tool_result(
        await mcp.call_tool(
            "dc_prepare_delete_record",
            {"collection_id": cid, "record_id": rid, "expected_version": 1},
        )
    )
    assert prep["ok"] is True
    tok = prep["confirmation_token"]

    ok_del = _parse_tool_result(
        await mcp.call_tool(
            "dc_delete_record",
            {
                "collection_id": cid,
                "record_id": rid,
                "expected_version": 1,
                "confirmation_token": tok,
            },
        )
    )
    assert ok_del["ok"] is True

    replay_del = _parse_tool_result(
        await mcp.call_tool(
            "dc_delete_record",
            {
                "collection_id": cid,
                "record_id": rid,
                "expected_version": 1,
                "confirmation_token": tok,
            },
        )
    )
    assert replay_del["ok"] is False
    assert replay_del["error"]["code"] == "FORBIDDEN"

    # Bob cannot read Alice's collection
    set_mcp_actor(
        Actor(principal_id=bob_id, principal_type=PrincipalType.OAUTH_CLIENT, is_mcp=True)
    )
    bob_res = _parse_tool_result(
        await mcp.call_tool("dc_describe_collection", {"collection_id": cid})
    )
    assert bob_res["ok"] is False
    assert bob_res["error"]["code"] == "NOT_FOUND"


def test_mcp_http_oauth_metadata_and_origin_guards(mcp_ctx):
    container, _, _, _, _, _ = mcp_ctx
    app = create_mcp_http_app(container.settings, container=container)
    client = TestClient(app)

    assert client.get("/health/live").status_code == 200
    prm = client.get("/.well-known/oauth-protected-resource")
    assert prm.status_code == 200
    assert prm.json()["resource"] == container.settings.mcp_public_url

    asm = client.get("/.well-known/oauth-authorization-server")
    assert asm.status_code == 200
    assert "S256" in asm.json()["code_challenge_methods_supported"]

    unauth = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert unauth.status_code == 401
    assert "WWW-Authenticate" in unauth.headers

    bad_origin = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Origin": "https://evil.example.com"},
    )
    assert bad_origin.status_code == 403


def test_mcp_response_size_cap():
    big = {"ok": True, "items": [{"v": "x" * 1000} for _ in range(20)]}
    capped = cap_tool_response(big, max_bytes=4096)
    assert capped["truncated"] is True
    assert len(capped["items"]) < 20
