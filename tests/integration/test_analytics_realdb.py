"""Analytics REST endpoints against a REAL MongoDB (mongomock mis-evaluates these pipelines).

Runs only when DC_TEST_MONGODB_URI is set (CI real-db job; locally e.g. a throwaway
`docker run -p 27117:27017 mongo:7.0`). Each run uses its own database and drops it.
It deliberately does not read MONGODB_URI, which may point at a real deployment.
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta

import fakeredis
import pytest
from data_collector.app import create_app
from data_collector.config import Settings
from pymongo import MongoClient

URI = os.environ.get("DC_TEST_MONGODB_URI", "")
pytestmark = pytest.mark.skipif(not URI, reason="DC_TEST_MONGODB_URI not set (needs real MongoDB)")

PW = "StrongPassword123!"
FIELDS = ["name", "city", "region", "categories", "rating", "email", "has_website", "dc_event"]
SCHEMA = {"type": "object", "properties": {k: {} for k in FIELDS}}
T0 = datetime(2026, 11, 1, 12, tzinfo=UTC)

# (region, has_website, categories, email, rating, city, day offset)
A_ROWS = [
    ("TX", False, ["dentist"], "a@x.io", 4.0, "Austin", 0),
    ("TX", False, ["dentist", "cafe"], None, 5.0, "Austin", 0),
    ("TX", True, ["cafe"], "b@x.io", 3.0, "Dallas", 1),
    ("CA", False, ["dentist"], "", 2.0, "LA", 1),
    (None, False, [], "c@x.io", None, "LA", 2),  # region missing -> unknown
    ("NY", None, ["lawyer"], "d@x.io", 4.5, "NYC", 2),  # has_website missing: not false
]


@pytest.fixture
def env():
    db_name = f"dc_test_{secrets.token_hex(4)}"
    mongo = MongoClient(URI, tz_aware=True)
    settings = Settings(
        app_env="test",
        jwt_secret_key="analytics-realdb-jwt-secret-key-32-bytes!",
        mongodb_db=db_name,
        rate_limit_read_per_minute=10_000,
        rate_limit_write_per_minute=10_000,
    )
    app = create_app(
        settings, mongo_client=mongo, redis_client=fakeredis.FakeRedis(), ensure_indexes=True
    )
    ctr = app.extensions["container"]
    db = ctr.mongo.db
    tokens = {}
    with app.test_client() as client:
        for name in ("alice", "bob"):
            ctr.auth_service.register_user(f"{name}@example.com", PW)
            tokens[name] = {
                "Authorization": "Bearer "
                + client.post(
                    "/api/v1/auth/login", json={"email": f"{name}@example.com", "password": PW}
                ).get_json()["access_token"]
            }

        def setup(user: str, slug: str) -> tuple[str, str, str]:
            h = tokens[user]
            wid = client.post(
                "/api/v1/workspaces", json={"slug": slug, "name": slug}, headers=h
            ).get_json()["id"]
            pid = client.post(
                f"/api/v1/workspaces/{wid}/projects",
                json={"slug": "leads", "name": "Leads"},
                headers=h,
            ).get_json()["id"]
            cid = client.post(
                f"/api/v1/projects/{pid}/collections",
                json={"slug": "leads-business-v2", "json_schema": SCHEMA},
                headers=h,
            ).get_json()["id"]
            return wid, pid, cid

        wa, pa, ca = setup("alice", "ws-alice")
        wb, pb, cb = setup("bob", "ws-bob")
        docs = []
        for region, hw, cats, email, rating, city, day in A_ROWS:
            d: dict = {"name": "x", "city": city, "categories": cats}
            if region is not None:
                d["region"] = region
            if hw is not None:
                d["has_website"] = hw
            if email is not None:
                d["email"] = email
            if rating is not None:
                d["rating"] = rating
            ts = T0 + timedelta(days=day)
            d["dc_event"] = {"observed_at": ts.isoformat().replace("+00:00", "Z")}
            docs.append(
                {
                    "workspace_id": wa,
                    "project_id": pa,
                    "collection_id": ca,
                    "data": d,
                    "version": 1,
                    "created_at": ts,
                    "updated_at": ts,
                    "created_by": "a",
                    "deleted_at": None,
                    "source": {},
                }
            )
        # Soft-deleted record in A: never counted.
        docs.append({**docs[0], "deleted_at": T0})
        # Bob's tenant: distinctive values that must never surface for Alice.
        for _ in range(7):
            docs.append(
                {
                    "workspace_id": wb,
                    "project_id": pb,
                    "collection_id": cb,
                    "data": {
                        "region": "LEAK",
                        "has_website": False,
                        "categories": ["leak"],
                        "city": "Leakville",
                        "rating": 1.0,
                        "dc_event": {"observed_at": "2020-01-01T00:00:00Z"},
                    },
                    "version": 1,
                    "created_at": T0 - timedelta(days=900),
                    "updated_at": T0,
                    "created_by": "b",
                    "deleted_at": None,
                    "source": {},
                }
            )
        db.records.insert_many(docs)
        yield {"client": client, "h": tokens, "ca": ca, "cb": cb, "wa": wa}
    mongo.drop_database(db_name)
    ctr.close()


def _post(env, cid, kind, body, user="alice"):
    return env["client"].post(
        f"/api/v1/collections/{cid}/analytics/{kind}", json=body, headers=env["h"][user]
    )


def test_region_count_where_has_website_false(env):
    r = _post(
        env,
        env["ca"],
        "aggregate",
        {
            "group_by": ["region"],
            "filter": {"field": "has_website", "op": "eq", "value": False},
        },
    )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    got = {row["group"]["region"]: row["count"] for row in body["rows"]}
    # NY row has has_website missing: it is NOT counted as false.
    assert got == {"TX": 2, "CA": 1, None: 1}
    assert body["coverage"]["matched"] == 4
    assert body["coverage"]["unknown"] == {"region": 1}
    assert body["coverage"]["freshness"]["min_created_at"].startswith("2026-11-01")
    unknown_row = next(row for row in body["rows"] if row["group"]["region"] is None)
    assert unknown_row["unknown_fields"] == ["region"]


def test_per_category_total_with_email_share(env):
    r = _post(
        env,
        env["ca"],
        "aggregate",
        {
            "group_by": ["categories"],
            "metrics": [
                {"op": "count", "as": "total"},
                {"op": "count", "field": "email", "as": "with_email"},
                {"op": "fill_rate", "field": "email", "as": "share"},
            ],
        },
    )
    rows = {row["group"]["categories"]: row for row in r.get_json()["rows"]}
    assert (rows["dentist"]["total"], rows["dentist"]["with_email"]) == (3, 1)  # "" is not an email
    assert rows["dentist"]["share"] == pytest.approx(1 / 3)
    assert (rows["cafe"]["total"], rows["cafe"]["with_email"]) == (2, 1)
    assert rows[None]["total"] == 1  # empty categories array -> unknown


def test_avg_and_p50_rating_per_city_top_n(env):
    r = _post(
        env,
        env["ca"],
        "aggregate",
        {
            "group_by": ["city"],
            "metrics": [{"op": "avg", "field": "rating"}, {"op": "p50", "field": "rating"}],
            "sort": [{"by": "avg_rating", "direction": "desc"}],
            "limit": 2,
        },
    )
    body = r.get_json()
    assert [row["group"]["city"] for row in body["rows"]] == ["Austin", "NYC"]
    assert body["rows"][0]["avg_rating"] == 4.5
    assert body["truncated"] is True


def test_records_per_day_and_nested_date(env):
    body = _post(env, env["ca"], "histogram", {"interval": "day"}).get_json()
    assert [(b["bucket"], b["count"]) for b in body["buckets"]] == [
        ("2026-11-01", 2),
        ("2026-11-02", 2),
        ("2026-11-03", 2),
    ]
    body = _post(
        env, env["ca"], "histogram", {"date_field": "dc_event.observed_at", "interval": "month"}
    ).get_json()
    assert body["buckets"][0]["bucket"] == "2026-11" and body["buckets"][0]["count"] == 6


def test_distinct_and_fields(env):
    body = _post(env, env["ca"], "distinct", {"field": "region"}).get_json()
    assert body["values"][0] == {"value": "TX", "count": 3}
    assert body["coverage"]["unknown"] == {"region": 1}
    fields = (
        env["client"]
        .get(f"/api/v1/collections/{env['ca']}/analytics/fields", headers=env["h"]["alice"])
        .get_json()
    )
    by = {f["field"]: f for f in fields["fields"]}
    assert by["has_website"]["types"] == {"bool": 5}
    assert by["dc_event.observed_at"]["groupable"] is True
    assert fields["total_records"] == 6


def test_isolation_across_every_analytics_surface(env):
    # Alice queries her own collection, trying to reach Bob's values via each knob.
    probes = [
        ("aggregate", {"group_by": ["region"]}),
        (
            "aggregate",
            {"group_by": ["region"], "filter": {"field": "region", "op": "eq", "value": "LEAK"}},
        ),
        (
            "aggregate",
            {"group_by": ["city"], "sort": [{"by": "city", "direction": "asc"}], "limit": 500},
        ),
        ("distinct", {"field": "categories", "limit": 200}),
        ("histogram", {"date_field": "dc_event.observed_at", "interval": "month"}),
    ]
    for kind, body in probes:
        r = _post(env, env["ca"], kind, body)
        assert r.status_code == 200, (kind, r.get_json())
        text = str(r.get_json())
        assert "LEAK" not in text and "Leakville" not in text and "leak" not in text
        assert "2020-01" not in text
    leaked = _post(
        env, env["ca"], "aggregate", {"filter": {"field": "region", "op": "eq", "value": "LEAK"}}
    ).get_json()
    assert leaked["coverage"]["matched"] == 0

    # Alice addressing Bob's collection id directly: 404 on every surface (no existence leak).
    for kind, body in probes:
        assert _post(env, env["cb"], kind, body).status_code == 404
    assert (
        env["client"]
        .get(f"/api/v1/collections/{env['cb']}/analytics/fields", headers=env["h"]["alice"])
        .status_code
        == 404
    )


def test_refusals_are_422(env):
    for body in (
        {"group_by": ["$where"]},
        {"group_by": ["unknown_field"]},
        {"metrics": [{"op": "$accumulator", "field": "rating"}]},
        {"filter": {"$where": "sleep(1000)"}},
        {"limit": 501},
    ):
        assert _post(env, env["ca"], "aggregate", body).status_code == 422, body
