"""Integration tests for tiered counts, query planner, isolated fulltext, and MCP tools."""

from __future__ import annotations

import fakeredis
import mongomock
from data_collector.app import create_app
from data_collector.config import Settings
from data_collector.mcp.tools import list_tool_names


def _register_and_login(app, client, email: str) -> str:
    app.extensions["container"].auth_service.register_user(email, "VeryStrongPassword123!")
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "VeryStrongPassword123!"},
    )
    assert login.status_code == 200
    return str(login.get_json()["access_token"])


def test_tiered_counts_batch_isolation_and_no_source_writes() -> None:
    cfg = Settings(
        app_env="test",
        jwt_secret_key="test-jwt-secret-key-at-least-32-chars!!",
        fulltext_search_enabled=False,
    )
    app = create_app(
        cfg,
        mongo_client=mongomock.MongoClient(),
        redis_client=fakeredis.FakeRedis(),
        ensure_indexes=True,
    )
    client = app.test_client()
    tok_a = _register_and_login(app, client, "alice@example.com")
    tok_b = _register_and_login(app, client, "bob@example.com")
    h_a = {"Authorization": f"Bearer {tok_a}"}
    h_b = {"Authorization": f"Bearer {tok_b}"}

    ws = client.post(
        "/api/v1/workspaces", json={"slug": "ws-cnt", "name": "Count WS"}, headers=h_a
    ).get_json()
    proj = client.post(
        f"/api/v1/workspaces/{ws['id']}/projects",
        json={"slug": "proj-cnt", "name": "Project Count"},
        headers=h_a,
    ).get_json()
    assert "id" in proj, proj
    col = client.post(
        f"/api/v1/projects/{proj['id']}/collections",
        json={"slug": "events", "schema_json": {}, "searchable_fields": ["msg"]},
        headers=h_a,
    ).get_json()
    assert "id" in col, col

    # Batch on cold cache returns 'pending' with value=None (never 0) and omits unauthorized.
    batch_cold = client.post(
        "/api/v1/collections/counts",
        json={"collection_ids": [col["id"]]},
        headers=h_a,
    )
    assert batch_cold.status_code == 200
    item = batch_cold.get_json()["items"][0]
    assert item["active"]["accuracy"] == "pending"
    assert item["active"]["value"] is None

    # Tenant B cannot see Tenant A's collection count in batch.
    batch_b = client.post(
        "/api/v1/collections/counts",
        json={"collection_ids": [col["id"]]},
        headers=h_b,
    )
    assert batch_b.status_code == 200
    assert batch_b.get_json()["items"] == []

    # Create 2 records, then query single count (computes bounded exact -> caches it).
    for i in range(2):
        r = client.post(
            f"/api/v1/collections/{col['id']}/records",
            json={"data": {"msg": f"hello {i}"}},
            headers=h_a,
        )
        assert r.status_code == 201

    c1 = client.get(f"/api/v1/collections/{col['id']}/record-count", headers=h_a)
    assert c1.status_code == 200
    assert c1.get_json()["active"]["value"] == 2
    assert c1.get_json()["active"]["accuracy"] == "exact_as_of"

    # Subsequent batch hit comes from cache.
    batch_warm = client.post(
        "/api/v1/collections/counts",
        json={"collection_ids": [col["id"]]},
        headers=h_a,
    )
    assert batch_warm.status_code == 200
    assert batch_warm.get_json()["items"][0]["active"]["value"] == 2
    assert batch_warm.get_json()["items"][0]["active"]["source"] == "cache"

    # Refresh returns 202 Accepted.
    ref = client.post(f"/api/v1/collections/{col['id']}/record-count/refresh", headers=h_a)
    assert ref.status_code == 202

    # Broad contains is blocked with 422 QUERY_NOT_INDEXED.
    bad_search = client.post(
        f"/api/v1/collections/{col['id']}/records/search",
        json={"filter": {"field": "msg", "op": "contains", "value": "hello"}},
        headers=h_a,
    )
    assert bad_search.status_code == 422
    assert bad_search.get_json()["error"]["code"] == "QUERY_NOT_INDEXED"

    # Fulltext disabled returns 503 SEARCH_INDEX_NOT_READY.
    ft_off = client.post(
        f"/api/v1/collections/{col['id']}/records/fulltext",
        json={"query": "hello"},
        headers=h_a,
    )
    assert ft_off.status_code == 503
    assert ft_off.get_json()["error"]["code"] == "SEARCH_INDEX_NOT_READY"


def test_fulltext_backfill_hydration_and_soft_delete_suppression() -> None:
    cfg = Settings(
        app_env="test",
        jwt_secret_key="test-jwt-secret-key-at-least-32-chars!!",
        fulltext_search_enabled=True,
        fulltext_search_backend="memory",
        search_backfill_enabled=True,
    )
    app = create_app(
        cfg,
        mongo_client=mongomock.MongoClient(),
        redis_client=fakeredis.FakeRedis(),
        ensure_indexes=True,
    )
    client = app.test_client()
    container = app.extensions["container"]

    tok_a = _register_and_login(app, client, "owner_ft@example.com")
    tok_b = _register_and_login(app, client, "other_ft@example.com")
    h_a = {"Authorization": f"Bearer {tok_a}"}
    h_b = {"Authorization": f"Bearer {tok_b}"}

    ws = client.post(
        "/api/v1/workspaces", json={"slug": "ws-ft", "name": "FT WS"}, headers=h_a
    ).get_json()
    proj = client.post(
        f"/api/v1/workspaces/{ws['id']}/projects",
        json={"slug": "proj-ft", "name": "Project FT"},
        headers=h_a,
    ).get_json()
    assert "id" in proj, proj
    col = client.post(
        f"/api/v1/projects/{proj['id']}/collections",
        json={"slug": "logs", "schema_json": {}, "searchable_fields": ["details"]},
        headers=h_a,
    ).get_json()
    assert "id" in col, col

    r1 = client.post(
        f"/api/v1/collections/{col['id']}/records",
        json={"data": {"details": {"message": "Payment failed at gateway"}}},
        headers=h_a,
    ).get_json()
    r2 = client.post(
        f"/api/v1/collections/{col['id']}/records",
        json={"data": {"details": {"message": "Payment succeeded"}}},
        headers=h_a,
    ).get_json()

    # Plan dry-run + backfill into memory search backend
    plan = container.search_indexer.plan_backfill(col["id"])
    assert plan["safe_to_index"] is True
    cp = container.search_indexer.backfill_collection(col["id"], batch_size=1)
    assert cp["processed_count"] == 2
    assert cp["coverage"] == "complete"

    # Search status reports ready & complete
    st = client.get(f"/api/v1/collections/{col['id']}/search/status", headers=h_a)
    assert st.status_code == 200
    assert st.get_json()["indexed_records"] == 2

    # Fulltext hit returns hydrated record + highlights
    ft = client.post(
        f"/api/v1/collections/{col['id']}/records/fulltext",
        json={"query": '"Payment failed"'},
        headers=h_a,
    )
    assert ft.status_code == 200
    items = ft.get_json()["items"]
    assert len(items) == 1
    assert items[0]["record"]["id"] == r1["id"]

    # Tenant B cannot access Tenant A's collection (404/403).
    ft_b = client.post(
        f"/api/v1/collections/{col['id']}/records/fulltext",
        json={"query": "Payment"},
        headers=h_b,
    )
    assert ft_b.status_code in (403, 404)

    # Soft-delete r1 in source MongoDB -> hydration suppresses stale hit!
    del_res = client.delete(
        f"/api/v1/collections/{col['id']}/records/{r1['id']}",
        json={"expected_version": r1["version"]},
        headers=h_a,
    )
    assert del_res.status_code == 200

    ft_after_del = client.post(
        f"/api/v1/collections/{col['id']}/records/fulltext",
        json={"query": "Payment"},
        headers=h_a,
    )
    assert ft_after_del.status_code == 200
    returned_ids = [it["record"]["id"] for it in ft_after_del.get_json()["items"]]
    assert r1["id"] not in returned_ids
    assert r2["id"] in returned_ids

    # New read-only MCP tools are registered
    tools = list_tool_names()
    assert "dc_get_collection_count" in tools
    assert "dc_fulltext_search" in tools
