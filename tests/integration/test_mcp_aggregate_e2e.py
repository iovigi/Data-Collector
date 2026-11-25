"""MCP SDK end-to-end: list tools, read instructions, run the describe -> distinct ->
aggregate -> histogram workflow over live Streamable HTTP, and probe tenant isolation.

Uses a real MongoDB when DC_TEST_MONGODB_URI is set (grouped results are asserted);
otherwise mongomock, where only ungrouped counts are trustworthy.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis
import httpx
import mongomock
import pytest
import uvicorn
from bson import ObjectId
from data_collector.config import Settings
from data_collector.container import build_container
from data_collector.domain.identities import Actor, PrincipalType
from data_collector.mcp.server_http import create_mcp_http_app
from mcp.client.streamable_http import streamable_http_client
from pymongo import MongoClient

from mcp import ClientSession

REAL_URI = os.environ.get("DC_TEST_MONGODB_URI", "")
SCOPES = ["workspace:read", "collection:read", "records:read"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def live():
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    db_name = f"dc_test_{secrets.token_hex(4)}"
    mongo: Any = MongoClient(REAL_URI, tz_aware=True) if REAL_URI else mongomock.MongoClient()
    settings = Settings(
        app_env="test",
        jwt_secret_key="mcp-agg-e2e-jwt-secret-key-32-bytes!!",
        allowed_origins=["http://127.0.0.1"],
        mcp_public_url=f"{base}/mcp",
        auth_issuer=base,
        oauth_mode="builtin",
        mongodb_db=db_name,
    )
    ctr = build_container(
        settings, mongo_client=mongo, redis_client=fakeredis.FakeRedis(), ensure_indexes=True
    )
    ua = ctr.auth_service.register_user("alice.agg@example.com", "StrongPassword123!")
    ub = ctr.auth_service.register_user("bob.agg@example.com", "StrongPassword123!")
    alice = Actor(principal_id=ua["id"], principal_type=PrincipalType.USER)
    bob = Actor(principal_id=ub["id"], principal_type=PrincipalType.USER)
    ws = ctr.collection_service.create_workspace(alice, slug="alice-agg", name="A")
    pj = ctr.collection_service.create_project(alice, ws["id"], slug="leads", name="L")
    col = ctr.collection_service.create_collection(
        alice,
        pj["id"],
        slug="leads-business-v2",
        schema_json={
            "type": "object",
            "properties": {k: {} for k in ("region", "has_website", "email", "categories")},
        },
    )
    ctr.collection_service.create_workspace(bob, slug="bob-agg", name="B")
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    rows = [
        ("TX", False, "a@x.io"),
        ("TX", False, None),
        ("TX", True, "b@x.io"),
        ("CA", False, "c@x.io"),
        (None, False, None),
    ]
    for i, (region, hw, email) in enumerate(rows):
        data: dict[str, Any] = {"has_website": hw, "categories": ["dentist"]}
        if region:
            data["region"] = region
        if email:
            data["email"] = email
        rec = ctr.records.insert_one(
            workspace_id=ws["id"],
            project_id=pj["id"],
            collection_id=col["id"],
            data=data,
            created_by=ua["id"],
            source={},
        )
        ctr.mongo.db.records.update_one(
            {"_id": ObjectId(rec["id"])},
            {"$set": {"created_at": t0 + timedelta(days=i % 2)}},
        )

    def token(user: dict[str, Any], fam: str) -> str:
        return ctr.oauth_service._mint_oauth_tokens(
            user_id=user["id"],
            email=user["email"],
            client_id="agg-e2e",
            scopes=SCOPES,
            resource=settings.mcp_public_url,
            family_id=fam,
        )["access_token"]

    app = create_mcp_http_app(settings, container=ctr)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            if httpx.get(f"{base}/health/live", timeout=0.5).status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    yield {"mcp": f"{base}/mcp", "alice": token(ua, "fa"), "bob": token(ub, "fb"), "cid": col["id"]}
    server.should_exit = True
    thread.join(timeout=3)
    if REAL_URI:
        mongo.drop_database(db_name)
    ctr.close()


async def _session(url: str, tok: str, calls: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    async with (
        httpx.AsyncClient(headers={"Authorization": f"Bearer {tok}"}, timeout=15.0) as http,
        streamable_http_client(url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        tools = await session.list_tools()
        out: dict[str, Any] = {
            "instructions": init.instructions or "",
            "tools": {t.name: (t.description or "") for t in tools.tools},
        }
        for name, args in calls:
            res = await session.call_tool(name, args)
            out[name] = json.loads(res.content[0].text)
        return out


def test_sdk_lists_tools_and_runs_aggregation_workflow(live):
    cid = live["cid"]
    out = asyncio.run(
        _session(
            live["mcp"],
            live["alice"],
            [
                ("dc_describe_collection", {"collection_id": cid}),
                ("dc_distinct_values", {"collection_id": cid, "field": "region"}),
                (
                    "dc_aggregate",
                    {
                        "collection_id": cid,
                        "filter": {"field": "has_website", "op": "eq", "value": False},
                    },
                ),
                ("dc_histogram", {"collection_id": cid, "interval": "day"}),
            ],
        )
    )
    for name in ("dc_aggregate", "dc_distinct_values", "dc_histogram", "dc_describe_collection"):
        assert name in out["tools"]
    assert "dc_describe_collection" in out["instructions"]
    assert "dc_aggregate" in out["instructions"] and "unknown" in out["instructions"]
    assert "fill_rate" in out["tools"]["dc_aggregate"]
    assert "has_website" in out["tools"]["dc_aggregate"]  # worked example present

    desc = out["dc_describe_collection"]
    assert desc["ok"] is True and desc["total_records"] == 5
    assert {f["field"] for f in desc["fields"]} >= {"region", "has_website", "categories"}

    agg = out["dc_aggregate"]
    assert agg["ok"] is True
    assert agg["rows"] == [{"count": 4}]
    assert agg["coverage"]["matched"] == 4

    if REAL_URI:
        assert out["dc_distinct_values"]["values"] == [
            {"value": "TX", "count": 3},
            {"value": "CA", "count": 1},
        ]
        assert out["dc_distinct_values"]["coverage"]["unknown"] == {"region": 1}
        assert [b["count"] for b in out["dc_histogram"]["buckets"]] == [3, 2]
        grouped = asyncio.run(
            _session(
                live["mcp"],
                live["alice"],
                [
                    (
                        "dc_aggregate",
                        {
                            "collection_id": cid,
                            "group_by": ["region"],
                            "metrics": [
                                {"op": "count"},
                                {"op": "count", "field": "email", "as": "with_email"},
                            ],
                            "filter": {"field": "has_website", "op": "eq", "value": False},
                        },
                    )
                ],
            )
        )["dc_aggregate"]
        got = {r["group"]["region"]: (r["count"], r["with_email"]) for r in grouped["rows"]}
        assert got == {"TX": (2, 1), "CA": (1, 1), None: (1, 0)}
        assert grouped["coverage"]["unknown"] == {"region": 1}


def test_other_tenant_cannot_aggregate_via_mcp(live):
    cid = live["cid"]
    out = asyncio.run(
        _session(
            live["mcp"],
            live["bob"],
            [
                ("dc_aggregate", {"collection_id": cid, "group_by": ["region"]}),
                ("dc_distinct_values", {"collection_id": cid, "field": "region"}),
                ("dc_histogram", {"collection_id": cid}),
                ("dc_describe_collection", {"collection_id": cid}),
            ],
        )
    )
    for name in ("dc_aggregate", "dc_distinct_values", "dc_histogram", "dc_describe_collection"):
        assert out[name]["ok"] is False
        assert out[name]["error"]["code"] == "NOT_FOUND"
