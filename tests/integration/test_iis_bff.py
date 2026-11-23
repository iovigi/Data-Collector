"""IIS-native hosting: Python BFF sessions/CSRF/allowlist, SPA serving, client IP, jobs."""

from __future__ import annotations

import threading
from typing import Any

import fakeredis
import mongomock
import pytest
from data_collector.app import create_app
from data_collector.bff import register_iis_ui_and_bff
from data_collector.bff.allowlist import is_allowed_backend_path
from data_collector.bff.csrf import create_csrf_token, is_trusted_origin, verify_csrf_token
from data_collector.bff.session_store import WebSessionStore
from data_collector.config import Settings
from data_collector.domain.exceptions import ServiceUnavailableError
from data_collector.hosting.client_ip import CloudflareClientIPMiddleware

ORIGIN = "https://data.example.test"
PASSWORD = "StrongPassword123!"


def _settings(tmp_path, **extra: Any) -> Settings:
    base: dict[str, Any] = {
        "app_env": "test",
        "jwt_secret_key": "bff-test-jwt-secret-key-at-least-32-bytes!",
        "web_session_secret": "bff-test-web-session-secret-32-bytes-long!",
        "allowed_origins": [ORIGIN],
        "storage_dir": str(tmp_path / "storage"),
    }
    base.update(extra)
    return Settings(**base)


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>DC</title><div id=root></div>")
    (d / "assets" / "index-abc123.js").write_text("console.log(1)")
    (d / "assets" / "index-abc123.js.map").write_text("{}")
    return d


@pytest.fixture
def bff(tmp_path, dist):
    settings = _settings(tmp_path)
    redis_client = fakeredis.FakeRedis()
    app = create_app(
        settings,
        mongo_client=mongomock.MongoClient(),
        redis_client=redis_client,
        ensure_indexes=True,
    )
    register_iis_ui_and_bff(app, str(dist))
    app.config["TESTING"] = True
    container = app.extensions["container"]
    container.auth_service.register_user("alice@example.com", PASSWORD)
    container.auth_service.register_user("bob@example.com", PASSWORD)
    yield app, container, redis_client
    container.close()


def _login(client, email: str = "alice@example.com"):
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )


def _csrf(client) -> str:
    cookie = client.get_cookie("dc_csrf")
    assert cookie is not None
    return cookie.value


def _unsafe_headers(client) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": _csrf(client)}


# ------------------------------------------------------------------ login / session


def test_login_sets_opaque_httponly_session_and_no_tokens(bff):
    app, _, redis_client = bff
    client = app.test_client()
    resp = _login(client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["authenticated"] is True
    assert "access_token" not in resp.get_data(as_text=True)
    assert "refresh_token" not in resp.get_data(as_text=True)

    set_cookies = resp.headers.getlist("Set-Cookie")
    sid_cookie = next(c for c in set_cookies if c.startswith("dc_sid="))
    assert "HttpOnly" in sid_cookie and "SameSite=Lax" in sid_cookie and "Path=/" in sid_cookie
    assert "Domain=" not in sid_cookie
    csrf_cookie = next(c for c in set_cookies if c.startswith("dc_csrf="))
    assert "HttpOnly" not in csrf_cookie

    sid = client.get_cookie("dc_sid").value
    # Raw session id is never used as a Redis key
    keys = [k.decode() for k in redis_client.keys("dc:web:sess:*")]
    assert keys and all(sid not in k for k in keys)


def test_login_rejects_foreign_origin_and_bad_credentials(bff):
    app, _, _ = bff
    client = app.test_client()
    r = client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    r = client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": PASSWORD},
    )
    assert r.status_code == 403  # neither Origin nor Referer
    r = client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "wrong-password!!"},
        headers={"Origin": ORIGIN},
    )
    assert r.status_code == 401
    assert client.get_cookie("dc_sid") is None


def test_login_replaces_preexisting_session_id(bff):
    app, _, redis_client = bff
    client = app.test_client()
    _login(client)
    first = client.get_cookie("dc_sid").value
    _login(client)
    second = client.get_cookie("dc_sid").value
    assert first != second
    assert len(redis_client.keys("dc:web:sess:*")) == 1


# ------------------------------------------------------------------ backend dispatch


def test_backend_requires_session_and_uses_api_auth(bff):
    app, _, _ = bff
    client = app.test_client()
    assert client.get("/api/backend/me").status_code == 401
    _login(client)
    me = client.get("/api/backend/me")
    assert me.status_code == 200
    assert me.get_json()["email"] == "alice@example.com"
    assert me.headers["Cache-Control"] == "no-store"
    assert me.headers.get("X-Request-Id")


def test_backend_state_change_requires_origin_and_session_bound_csrf(bff):
    app, _, _ = bff
    alice = app.test_client()
    bob = app.test_client()
    _login(alice)
    _login(bob, "bob@example.com")
    payload = {"slug": "alpha", "name": "Alpha"}

    assert alice.post("/api/backend/workspaces", json=payload).status_code == 403  # no token
    r = alice.post(
        "/api/backend/workspaces",
        json=payload,
        headers={"Origin": "https://evil.example", "X-CSRF-Token": _csrf(alice)},
    )
    assert r.status_code == 403  # wrong origin
    # Bob's (valid) CSRF token must not work with Alice's session
    alice.set_cookie("dc_csrf", _csrf(bob))
    r = alice.post(
        "/api/backend/workspaces",
        json=payload,
        headers={"Origin": ORIGIN, "X-CSRF-Token": _csrf(bob)},
    )
    assert r.status_code == 403

    alice2 = app.test_client()
    _login(alice2)
    r = alice2.post("/api/backend/workspaces", json=payload, headers=_unsafe_headers(alice2))
    assert r.status_code == 201, r.get_data(as_text=True)
    wid = r.get_json()["id"]
    listed = alice2.get("/api/backend/workspaces").get_json()["items"]
    assert [w["id"] for w in listed] == [wid]
    # Bob cannot see Alice's workspace through the BFF either
    assert bob.get(f"/api/backend/workspaces/{wid}").status_code in (403, 404)


def test_backend_allowlist_and_traversal(bff):
    app, _, _ = bff
    client = app.test_client()
    _login(client)
    for path in (
        "/api/backend/auth/login",
        "/api/backend/admin/users",
        "/api/backend/workspaces/../auth/refresh",
        "/api/backend/workspaces/%2e%2e/me",
        "/api/backend/collections/zzz/records",
    ):
        assert client.get(path).status_code in (403, 404), path
    assert not is_allowed_backend_path("workspaces/..%2fme")
    assert not is_allowed_backend_path("/me")
    assert not is_allowed_backend_path("http://evil/me")
    assert is_allowed_backend_path("collections/" + "a" * 24 + "/records/search")


def test_backend_preserves_status_codes_and_headers(bff):
    app, _, _ = bff
    client = app.test_client()
    _login(client)
    h = _unsafe_headers(client)
    r = client.post("/api/backend/workspaces", json={"slug": "x"}, headers=h)
    assert r.status_code == 422
    assert r.get_json()["error"]["code"] == "VALIDATION_ERROR"
    r = client.get("/api/backend/workspaces/" + "b" * 24)
    assert r.status_code in (403, 404)
    assert r.get_json()["error"]["request_id"].startswith("req_")


def test_logout_revokes_refresh_family_and_session(bff):
    app, container, redis_client = bff
    client = app.test_client()
    _login(client)
    sid_key = redis_client.keys("dc:web:sess:*")[0]
    import json

    refresh_token = json.loads(redis_client.get(sid_key))["refresh_token"]
    # logout without CSRF is refused
    assert client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
    r = client.post("/api/auth/logout", headers=_unsafe_headers(client))
    assert r.status_code == 200
    assert redis_client.keys("dc:web:sess:*") == []
    assert client.get("/api/backend/me").status_code == 401
    with pytest.raises(Exception):  # noqa: B017 - family revoked
        container.auth_service.refresh(refresh_token)


def test_refresh_rotation_is_single_flight_across_concurrent_requests(bff):
    app, container, redis_client = bff
    client = app.test_client()
    _login(client)
    sid = client.get_cookie("dc_sid").value
    store = WebSessionStore(redis_client, 3600)
    sess = store.get(sid)
    sess["expires_at"] = 0  # force "needs refresh"
    store._write(sid, sess)

    results: list[Any] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(store.refresh(sid, container.auth_service))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert all(r is not None for r in results)
    # every caller ends up with the same rotated token pair; no replay revoked the family
    assert len({r["refresh_token"] for r in results}) == 1
    assert client.get("/api/backend/me").status_code == 200


def test_redis_down_fails_closed(tmp_path, dist):
    class DeadRedis(fakeredis.FakeRedis):
        def get(self, *a, **k):  # noqa: D401
            raise ConnectionError("down")

        def set(self, *a, **k):
            raise ConnectionError("down")

    settings = _settings(tmp_path)
    app = create_app(
        settings, mongo_client=mongomock.MongoClient(), redis_client=DeadRedis(), ensure_indexes=True
    )
    register_iis_ui_and_bff(app, str(dist))
    app.extensions["container"].auth_service.register_user("c@example.com", PASSWORD)
    client = app.test_client()
    r = client.post(
        "/api/auth/login",
        json={"email": "c@example.com", "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert r.status_code == 503
    assert client.get_cookie("dc_sid") is None
    client.set_cookie("dc_sid", "whatever")
    assert client.get("/api/backend/me").status_code == 503
    with pytest.raises(ServiceUnavailableError):
        WebSessionStore(DeadRedis(), 60).get("x")


def test_csrf_helpers():
    tok = create_csrf_token("s" * 40, "sid-1")
    assert verify_csrf_token("s" * 40, "sid-1", tok, tok)
    assert not verify_csrf_token("s" * 40, "sid-2", tok, tok)
    assert not verify_csrf_token("s" * 40, "sid-1", tok, tok + "x")
    assert not verify_csrf_token("t" * 40, "sid-1", tok, tok)
    assert is_trusted_origin(None, ORIGIN + "/w/x", [ORIGIN])
    assert not is_trusted_origin(None, "https://data.example.test.evil.com/", [ORIGIN])


# ------------------------------------------------------------------ SPA serving


def test_spa_routes_assets_and_no_fallback_for_api(bff):
    app, _, _ = bff
    client = app.test_client()
    for path in ("/", "/login", "/w/abc/overview", "/onboarding/create-workspace", "/developer/api"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.mimetype == "text/html"
        assert r.headers["Cache-Control"] == "no-store"
        assert "default-src 'self'" in r.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]

    a = client.get("/assets/index-abc123.js")
    assert a.status_code == 200
    assert "immutable" in a.headers["Cache-Control"]
    assert "javascript" in a.mimetype
    assert client.get("/assets/index-abc123.js.map").status_code == 404
    assert client.get("/assets/../index.html").status_code == 404

    for path in ("/api/v1/does-not-exist", "/api/nothing", "/random", "/mcp", "/oauth/x"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.is_json, path


# ------------------------------------------------------------------ client IP


def test_cloudflare_client_ip_only_from_cloudflare_peers():
    seen: dict[str, str] = {}

    def app(environ, start_response):
        seen["ip"] = environ["REMOTE_ADDR"]
        seen["xff"] = environ.get("HTTP_X_FORWARDED_FOR", "")
        start_response("200 OK", [])
        return [b""]

    mw = CloudflareClientIPMiddleware(app)
    mw({"REMOTE_ADDR": "172.68.1.1", "HTTP_CF_CONNECTING_IP": "203.0.113.9"}, lambda *a: None)
    assert seen["ip"] == "203.0.113.9"
    mw(
        {
            "REMOTE_ADDR": "198.51.100.7",
            "HTTP_CF_CONNECTING_IP": "203.0.113.9",
            "HTTP_X_FORWARDED_FOR": "1.2.3.4",
        },
        lambda *a: None,
    )
    assert seen["ip"] == "198.51.100.7"
    assert seen["xff"] == ""
    mw({"REMOTE_ADDR": "172.68.1.1", "HTTP_CF_CONNECTING_IP": "not-an-ip"}, lambda *a: None)
    assert seen["ip"] == "172.68.1.1"


# ------------------------------------------------------------------ config


def test_production_requires_distinct_web_session_secret():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    common = {
        "app_env": "production",
        "jwt_secret_key": "j" * 40,
        "allowed_origins": [ORIGIN],
        "mcp_public_url": ORIGIN + "/mcp",
        "auth_issuer": ORIGIN,
        "oauth_rsa_private_key_pem": pem,
    }
    with pytest.raises(ValueError):
        Settings(**common, web_session_secret="j" * 40)  # same as JWT secret
    with pytest.raises(ValueError):
        Settings(**common, web_session_secret="short")
    assert Settings(**common, web_session_secret="w" * 40).web_session_secret == "w" * 40

    # API-only production deployments may omit it, but the browser BFF refuses to start.
    no_bff = Settings(**common)
    app = create_app(
        no_bff, mongo_client=mongomock.MongoClient(), redis_client=fakeredis.FakeRedis()
    )
    with pytest.raises(RuntimeError):
        register_iis_ui_and_bff(app, "")


# ------------------------------------------------------------------ async jobs + worker


def test_async_import_export_executed_by_windows_worker(tmp_path):
    from data_collector.workers.main import WindowsSimpleWorker, build_worker

    redis_client = fakeredis.FakeRedis()
    settings = _settings(tmp_path, jobs_async=True)
    app = create_app(
        settings, mongo_client=mongomock.MongoClient(), redis_client=redis_client, ensure_indexes=True
    )
    container = app.extensions["container"]
    assert container.job_queue is not None
    container.auth_service.register_user("ops@example.com", PASSWORD)
    client = app.test_client()
    tok = client.post(
        "/api/v1/auth/login", json={"email": "ops@example.com", "password": PASSWORD}
    ).get_json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    wid = client.post("/api/v1/workspaces", json={"slug": "jobs-ws", "name": "W"}, headers=h).get_json()[
        "id"
    ]
    pid = client.post(
        f"/api/v1/workspaces/{wid}/projects", json={"slug": "proj-a", "name": "P"}, headers=h
    ).get_json()["id"]
    cid = client.post(
        f"/api/v1/projects/{pid}/collections",
        json={
            "slug": "coll-a",
            "schema_json": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
        headers=h,
    ).get_json()["id"]

    imp = client.post(
        f"/api/v1/collections/{cid}/imports?format=jsonl",
        data=b'{"name": "a"}\n{"name": "b"}\n',
        headers=h,
    )
    assert imp.status_code == 202
    assert imp.get_json()["state"] == "queued"  # not executed in the request
    exp = client.post(f"/api/v1/collections/{cid}/exports", json={"format": "jsonl"}, headers=h)
    assert exp.status_code == 202

    # The worker process runs jobs with a fresh container built from settings, exactly like
    # the Windows service. Point it at the same in-memory backends.
    import data_collector.workers.jobs as jobs_mod

    original = jobs_mod.build_container
    jobs_mod.build_container = lambda: container  # type: ignore[assignment]
    container.close = lambda: None  # type: ignore[method-assign]
    try:
        worker = build_worker(redis_client, windows=True)
        assert isinstance(worker, WindowsSimpleWorker)
        worker.work(burst=True)
    finally:
        jobs_mod.build_container = original

    imp_job = client.get(f"/api/v1/jobs/{imp.get_json()['id']}", headers=h).get_json()
    assert imp_job["state"] == "completed", imp_job
    records = client.get(f"/api/v1/collections/{cid}/records", headers=h).get_json()
    assert len(records["items"]) == 2
    exp_job = client.get(f"/api/v1/jobs/{exp.get_json()['id']}", headers=h).get_json()
    assert exp_job["state"] == "completed", exp_job


def test_enqueue_failure_marks_job_failed_and_returns_503(tmp_path):
    class NoQueueRedis(fakeredis.FakeRedis):
        def pipeline(self, *a, **k):
            raise ConnectionError("queue down")

    settings = _settings(tmp_path, jobs_async=True, rate_limit_fail_closed_mutations=False)
    app = create_app(
        settings,
        mongo_client=mongomock.MongoClient(),
        redis_client=NoQueueRedis(),
        ensure_indexes=True,
    )
    container = app.extensions["container"]
    container.auth_service.register_user("q@example.com", PASSWORD)
    client = app.test_client()
    tok = client.post(
        "/api/v1/auth/login", json={"email": "q@example.com", "password": PASSWORD}
    ).get_json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    wid = client.post("/api/v1/workspaces", json={"slug": "queue-ws", "name": "W"}, headers=h).get_json()[
        "id"
    ]
    pid = client.post(
        f"/api/v1/workspaces/{wid}/projects", json={"slug": "proj-b", "name": "P"}, headers=h
    ).get_json()["id"]
    cid = client.post(
        f"/api/v1/projects/{pid}/collections",
        json={"slug": "coll-b", "schema_json": {"type": "object"}},
        headers=h,
    ).get_json()["id"]
    r = client.post(f"/api/v1/collections/{cid}/exports", json={"format": "jsonl"}, headers=h)
    assert r.status_code == 503
    jobs = client.get(f"/api/v1/workspaces/{wid}/jobs", headers=h).get_json()["items"]
    assert jobs and jobs[0]["state"] == "failed"
