"""Two-step collection delete: RBAC, token/slug checks, isolation, dependents, audit, limits."""

from __future__ import annotations

import fakeredis
import mongomock
import pytest
from data_collector.app import create_app
from data_collector.config import Settings
from data_collector.infrastructure.crypto import sign_intent_token

PW = "StrongPassword123!"
SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}}


@pytest.fixture
def ctx():
    settings = Settings(
        app_env="test",
        jwt_secret_key="collection-delete-jwt-secret-key-32-bytes!",
        allowed_origins=["http://localhost:3000"],
        rate_limit_write_per_minute=10_000,
        rate_limit_read_per_minute=10_000,
    )
    redis = fakeredis.FakeRedis()
    app = create_app(
        settings,
        mongo_client=mongomock.MongoClient(),
        redis_client=redis,
        ensure_indexes=True,
    )
    app.config["TESTING"] = True
    ctr = app.extensions["container"]
    users = {
        name: ctr.auth_service.register_user(f"{name}.cdel@example.com", PW)
        for name in ("owner", "admin", "editor", "viewer")
    }
    with app.test_client() as client:
        headers = {}
        for name in users:
            tok = client.post(
                "/api/v1/auth/login", json={"email": f"{name}.cdel@example.com", "password": PW}
            ).get_json()["access_token"]
            headers[name] = {"Authorization": f"Bearer {tok}"}

        h = headers["owner"]
        wid = client.post(
            "/api/v1/workspaces", json={"slug": "cdel-ws", "name": "CDel"}, headers=h
        ).get_json()["id"]
        for role in ("admin", "editor", "viewer"):
            assert (
                client.post(
                    f"/api/v1/workspaces/{wid}/members",
                    json={"principal_id": users[role]["id"], "role": role},
                    headers=h,
                ).status_code
                == 200
            )
        pid = client.post(
            f"/api/v1/workspaces/{wid}/projects", json={"slug": "proj", "name": "P"}, headers=h
        ).get_json()["id"]

        def make_collection(slug: str, n_records: int, n_trashed: int = 0) -> str:
            cid = client.post(
                f"/api/v1/projects/{pid}/collections",
                json={"slug": slug, "json_schema": SCHEMA},
                headers=h,
            ).get_json()["id"]
            ids = []
            for i in range(n_records):
                rec = client.post(
                    f"/api/v1/collections/{cid}/records",
                    json={"data": {"name": f"r{i}"}},
                    headers=h,
                ).get_json()
                ids.append(rec["id"])
            for rid in ids[:n_trashed]:
                assert (
                    client.delete(
                        f"/api/v1/collections/{cid}/records/{rid}",
                        json={"expected_version": 1},
                        headers=h,
                    ).status_code
                    == 200
                )
            return cid

        yield {
            "client": client,
            "ctr": ctr,
            "redis": redis,
            "h": headers,
            "users": users,
            "wid": wid,
            "pid": pid,
            "make_collection": make_collection,
        }
    ctr.close()


def _prepare(client, cid, headers):
    return client.post(f"/api/v1/collections/{cid}/prepare-delete", headers=headers)


def _delete(client, cid, headers, token, slug):
    return client.delete(
        f"/api/v1/collections/{cid}",
        json={"confirmation_token": token, "confirm_slug": slug},
        headers=headers,
    )


def test_owner_prepares_and_deletes_and_dependents_are_removed(ctx):
    client, ctr, h = ctx["client"], ctx["ctr"], ctx["h"]["owner"]
    db = ctr.mongo.db
    victim = ctx["make_collection"]("leads-business", 6, n_trashed=2)
    keeper = ctx["make_collection"]("leads-business-v2", 3, n_trashed=1)

    # Dependents: saved queries on both, a key restricted to victim+keeper, a queued job.
    for cid in (victim, keeper):
        assert (
            client.post(
                f"/api/v1/collections/{cid}/saved-queries", json={"name": "all"}, headers=h
            ).status_code
            == 201
        )
    key = client.post(
        "/api/v1/keys",
        json={
            "workspace_id": ctx["wid"],
            "name": "producer",
            "scopes": ["records:read", "records:write"],
            "allowed_collection_ids": [victim, keeper],
        },
        headers=h,
    )
    assert key.status_code == 201, key.get_json()
    only_victim_key = client.post(
        "/api/v1/keys",
        json={
            "workspace_id": ctx["wid"],
            "name": "old-producer",
            "scopes": ["records:read"],
            "allowed_collection_ids": [victim],
        },
        headers=h,
    ).get_json()
    db.jobs.insert_one(
        {
            "workspace_id": ctx["wid"],
            "type": "import",
            "state": "queued",
            "params": {"collection_id": victim},
        }
    )

    prep = _prepare(client, victim, h)
    assert prep.status_code == 200, prep.get_json()
    body = prep.get_json()
    assert body["slug"] == "leads-business"
    assert body["records"] == {"active": 4, "trashed": 2, "total": 6}
    assert body["saved_queries"]["count"] == 1
    assert body["active_jobs"]["count"] == 1
    assert body["api_keys_restricted_to_collection"] == 2
    assert body["expires_in_seconds"] == 300

    res = _delete(client, victim, h, body["confirmation_token"], "leads-business")
    assert res.status_code == 200, res.get_json()
    out = res.get_json()
    assert out["deleted"] is True
    assert out["records_deleted"] == 6
    assert out["saved_queries_deleted"] == 1
    assert out["jobs_cancelled"] == 1
    assert out["api_keys_detached"] == 2
    assert out["correlation_id"] == body["correlation_id"]

    # Gone, including trash, and no dangling references anywhere.
    assert client.get(f"/api/v1/collections/{victim}", headers=h).status_code == 404
    assert db.collections.count_documents({"_id": __import__("bson").ObjectId(victim)}) == 0
    assert db.records.count_documents({"collection_id": victim}) == 0
    assert db.saved_queries.count_documents({"collection_id": victim}) == 0
    assert db.api_keys.count_documents({"allowed_collection_ids": victim}) == 0
    assert db.idempotency_keys.count_documents({"scope": f"{ctx['wid']}:{victim}"}) == 0
    assert db.jobs.find_one({"params.collection_id": victim})["state"] == "cancelled"
    listed = client.get(f"/api/v1/projects/{ctx['pid']}/collections", headers=h).get_json()
    assert [c["slug"] for c in listed["items"]] == ["leads-business-v2"]

    # A key whose only collection was deleted keeps an EMPTY allowlist (access to nothing),
    # never None (which would mean "all collections").
    doc = db.api_keys.find_one({"prefix": only_victim_key["prefix"]})
    assert doc["allowed_collection_ids"] == []
    ko = {"X-API-Key": only_victim_key["api_key"]}
    assert client.get(f"/api/v1/collections/{keeper}/records", headers=ko).status_code == 403

    # The same-workspace sibling collection is untouched.
    assert db.records.count_documents({"collection_id": keeper}) == 3
    assert db.records.count_documents({"collection_id": keeper, "deleted_at": {"$ne": None}}) == 1
    assert db.saved_queries.count_documents({"collection_id": keeper}) == 1
    assert db.api_keys.count_documents({"allowed_collection_ids": keeper}) == 1
    assert client.get(f"/api/v1/collections/{keeper}/records", headers=h).status_code == 200

    # Audit: prepare + delete with actor, slug, record count and correlation id.
    ev = db.audit_events.find_one({"action": "collection.delete", "decision": "allow"})
    assert ev["actor"] == ctx["users"]["owner"]["id"]
    assert ev["tenant"] == ctx["wid"]
    assert ev["metadata"]["slug"] == "leads-business"
    assert ev["metadata"]["record_count"] == 6
    assert ev["metadata"]["correlation_id"] == body["correlation_id"]
    assert (
        db.audit_events.count_documents(
            {
                "action": "collection.delete_prepare",
                "metadata.correlation_id": body["correlation_id"],
            }
        )
        == 1
    )

    # The token is single-use.
    again = _delete(client, victim, h, body["confirmation_token"], "leads-business")
    assert again.status_code == 404


def test_admin_can_delete(ctx):
    client = ctx["client"]
    cid = ctx["make_collection"]("admin-delete-me", 1)
    prep = _prepare(client, cid, ctx["h"]["admin"])
    assert prep.status_code == 200
    res = _delete(
        client, cid, ctx["h"]["admin"], prep.get_json()["confirmation_token"], "admin-delete-me"
    )
    assert res.status_code == 200
    assert res.get_json()["records_deleted"] == 1


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_editor_and_viewer_are_forbidden(ctx, role):
    client = ctx["client"]
    cid = ctx["make_collection"](f"{role}-cannot", 2)
    assert _prepare(client, cid, ctx["h"][role]).status_code == 403
    # Even holding an owner-issued token, the DELETE itself is refused.
    tok = _prepare(client, cid, ctx["h"]["owner"]).get_json()["confirmation_token"]
    assert _delete(client, cid, ctx["h"][role], tok, f"{role}-cannot").status_code == 403
    assert ctx["ctr"].mongo.db.records.count_documents({"collection_id": cid}) == 2
    denies = ctx["ctr"].mongo.db.audit_events.count_documents(
        {"target": f"collection:{cid}", "decision": "deny", "actor": ctx["users"][role]["id"]}
    )
    assert denies == 2


def test_collection_scoped_key_is_forbidden_even_with_scope(ctx):
    client, h = ctx["client"], ctx["h"]["owner"]
    cid = ctx["make_collection"]("scoped-key-target", 1)
    key = client.post(
        "/api/v1/keys",
        json={
            "workspace_id": ctx["wid"],
            "name": "scoped",
            "scopes": ["collection:read", "collection:delete"],
            "allowed_collection_ids": [cid],
        },
        headers=h,
    ).get_json()["api_key"]
    kh = {"X-API-Key": key}
    assert _prepare(client, cid, kh).status_code == 403
    tok = _prepare(client, cid, h).get_json()["confirmation_token"]
    assert _delete(client, cid, kh, tok, "scoped-key-target").status_code == 403
    assert ctx["ctr"].mongo.db.records.count_documents({"collection_id": cid}) == 1


def test_capabilities_flag(ctx):
    client, wid = ctx["client"], ctx["wid"]
    feats = {
        role: client.get(
            f"/api/v1/workspaces/{wid}/capabilities", headers=ctx["h"][role]
        ).get_json()["features"]["can_delete_collections"]
        for role in ("owner", "admin", "editor", "viewer")
    }
    assert feats == {"owner": True, "admin": True, "editor": False, "viewer": False}


def test_wrong_slug_expired_and_foreign_tokens_are_refused(ctx):
    client, ctr, h = ctx["client"], ctx["ctr"], ctx["h"]["owner"]
    a = ctx["make_collection"]("coll-a", 2)
    b = ctx["make_collection"]("coll-b", 2)
    db = ctr.mongo.db

    tok_a = _prepare(client, a, h).get_json()["confirmation_token"]
    # Wrong slug: refused, token NOT consumed (user can retype).
    r = _delete(client, a, h, tok_a, "coll-b")
    assert r.status_code == 422
    # Token for another collection.
    tok_b = _prepare(client, b, h).get_json()["confirmation_token"]
    assert _delete(client, a, h, tok_b, "coll-a").status_code == 403
    # Tampered / garbage token.
    assert _delete(client, a, h, tok_a + "x", "coll-a").status_code == 403
    # Expired token, correctly signed for the right collection.
    expired = sign_intent_token(
        {
            "op": "delete_collection",
            "actor": ctx["users"]["owner"]["id"],
            "ws": ctx["wid"],
            "cid": a,
            "slug": "coll-a",
            "corr": "cdel_test",
        },
        ctr.settings.intent_secret_key,
        ttl_seconds=-10,
    )
    assert _delete(client, a, h, expired, "coll-a").status_code == 403
    # Another user's token.
    tok_admin = _prepare(client, a, ctx["h"]["admin"]).get_json()["confirmation_token"]
    assert _delete(client, a, h, tok_admin, "coll-a").status_code == 403

    assert db.records.count_documents({"collection_id": a}) == 2
    assert db.records.count_documents({"collection_id": b}) == 2
    reasons = {
        e["metadata"]["reason"]
        for e in db.audit_events.find({"action": "collection.delete", "decision": "deny"})
    }
    assert {"slug_mismatch", "token_mismatch", "invalid_or_expired_token"} <= reasons

    # The original token still works after the wrong-slug attempt.
    assert _delete(client, a, h, tok_a, "coll-a").status_code == 200
    assert db.records.count_documents({"collection_id": b}) == 2


def test_other_workspace_is_untouched_and_cannot_see(ctx):
    client, ctr, h = ctx["client"], ctx["ctr"], ctx["h"]["owner"]
    # Second workspace owned by the editor, with a collection of the same slug.
    he = ctx["h"]["editor"]
    wid2 = client.post(
        "/api/v1/workspaces", json={"slug": "other-ws", "name": "Other"}, headers=he
    ).get_json()["id"]
    pid2 = client.post(
        f"/api/v1/workspaces/{wid2}/projects", json={"slug": "proj", "name": "P"}, headers=he
    ).get_json()["id"]
    cid2 = client.post(
        f"/api/v1/projects/{pid2}/collections",
        json={"slug": "leads-contact", "json_schema": SCHEMA},
        headers=he,
    ).get_json()["id"]
    for i in range(3):
        client.post(
            f"/api/v1/collections/{cid2}/records", json={"data": {"name": str(i)}}, headers=he
        )

    cid = ctx["make_collection"]("leads-contact", 4)
    # The first workspace's owner is not a member of wid2: 404, no existence leak.
    assert _prepare(client, cid2, h).status_code == 404

    tok = _prepare(client, cid, h).get_json()["confirmation_token"]
    assert _delete(client, cid, h, tok, "leads-contact").get_json()["records_deleted"] == 4
    assert ctr.mongo.db.records.count_documents({"collection_id": cid2}) == 3
    assert client.get(f"/api/v1/collections/{cid2}", headers=he).status_code == 200


def test_delete_costs_one_write_against_rate_limiter(ctx):
    client, redis, h = ctx["client"], ctx["redis"], ctx["h"]["owner"]
    cid = ctx["make_collection"]("bulk-target", 40, n_trashed=5)
    owner_id = ctx["users"]["owner"]["id"]
    pattern = f"rl:actor:{owner_id}:w:*"

    def writes() -> int:
        return sum(int(redis.get(k) or 0) for k in redis.scan_iter(pattern))

    tok = _prepare(client, cid, h).get_json()["confirmation_token"]
    before = writes()
    res = _delete(client, cid, h, tok, "bulk-target")
    assert res.status_code == 200
    assert res.get_json()["records_deleted"] == 40
    assert writes() - before == 1


def test_records_and_writes_refused_while_deleting(ctx):
    """A collection left in 'deleting' (e.g. crash mid-delete) is hidden but re-deletable."""
    client, ctr, h = ctx["client"], ctx["ctr"], ctx["h"]["owner"]
    cid = ctx["make_collection"]("half-deleted", 2)
    ctr.collections.set_status(ctx["wid"], cid, "deleting")
    assert client.get(f"/api/v1/collections/{cid}", headers=h).status_code == 404
    assert (
        client.post(
            f"/api/v1/collections/{cid}/records", json={"data": {"name": "x"}}, headers=h
        ).status_code
        == 404
    )
    prep = _prepare(client, cid, h)
    assert prep.status_code == 200
    assert prep.get_json()["status"] == "deleting"
    res = _delete(client, cid, h, prep.get_json()["confirmation_token"], "half-deleted")
    assert res.get_json()["records_deleted"] == 2


def test_openapi_documents_delete(ctx):
    spec = ctx["client"].get("/api/v1/openapi.json").get_json()
    item = spec["paths"]["/api/v1/collections/{cid}"]
    assert "delete" in item
    assert item["delete"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "DeleteCollectionRequest"
    )
    assert "post" in spec["paths"]["/api/v1/collections/{cid}/prepare-delete"]


def test_mcp_actor_is_refused_even_with_writes_enabled(ctx):
    from data_collector.domain.exceptions import AuthorizationError
    from data_collector.domain.identities import Actor, PrincipalType

    cid = ctx["make_collection"]("mcp-cannot", 1)
    mcp_actor = Actor(
        principal_id=ctx["users"]["owner"]["id"],
        principal_type=PrincipalType.OAUTH_CLIENT,
        client_id="some-mcp-client",
        is_mcp=True,
        mcp_allow_writes=True,
    )
    with pytest.raises(AuthorizationError):
        ctx["ctr"].collection_deletion.prepare(mcp_actor, cid)
    assert ctx["ctr"].mongo.db.records.count_documents({"collection_id": cid}) == 1
