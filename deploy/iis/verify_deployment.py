"""End-to-end verification of a deployed Data Collector (browser BFF flow + API + jobs).

Drives the public site exactly as the Admin UI does (cookies, CSRF header, /api/backend),
plus direct API-key access. Uses dedicated test accounts; everything it creates lives in a
fresh workspace that is archived at the end.

    set DC_E2E_OWNER_EMAIL / DC_E2E_OWNER_PASSWORD / DC_E2E_VIEWER_EMAIL / DC_E2E_VIEWER_PASSWORD
    python verify_deployment.py https://data.devart.solutions [--resolve 104.21.80.234]

``--resolve`` pins the hostname to an IP (e.g. a Cloudflare edge) for this process only,
bypassing a hosts-file entry that points the name at 127.0.0.1.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import socket
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -- ' + detail) if detail else ''}")
    return ok


def pin_dns(host: str, ip: str) -> None:
    real = socket.getaddrinfo

    def fake(h: Any, *a: Any, **k: Any) -> Any:
        return real(ip if h == host else h, *a, **k)

    socket.getaddrinfo = fake  # type: ignore[assignment]


class Browser:
    """Minimal browser-like client: cookie jar, Origin header, CSRF double-submit."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.c = httpx.Client(base_url=base, timeout=60, follow_redirects=False)

    def csrf(self) -> str:
        for name in ("__Host-dc_csrf", "dc_csrf"):
            v = self.c.cookies.get(name)
            if v:
                return v
        return ""

    def call(self, method: str, path: str, *, csrf: bool = True, **kw: Any) -> httpx.Response:
        headers = dict(kw.pop("headers", {}) or {})
        if method != "GET":
            headers.setdefault("Origin", self.base)
            if csrf:
                headers.setdefault("X-CSRF-Token", self.csrf())
        return self.c.request(method, path, headers=headers, **kw)

    def api(self, method: str, path: str, **kw: Any) -> httpx.Response:
        return self.call(method, "/api/backend/" + path.lstrip("/"), **kw)

    def login(self, email: str, password: str) -> httpx.Response:
        return self.call("POST", "/api/auth/login", csrf=False, json={"email": email, "password": password})


def wait_job(b: Browser, jid: str, timeout: float = 120) -> dict[str, Any]:
    deadline = time.time() + timeout
    job: dict[str, Any] = {}
    while time.time() < deadline:
        job = b.api("GET", f"jobs/{jid}").json()
        if job.get("state") in ("completed", "failed", "cancelled"):
            return job
        time.sleep(1.5)
    return job


def run(base: str) -> None:
    host = urlparse(base).netloc
    owner_email = os.environ["DC_E2E_OWNER_EMAIL"]
    owner_pw = os.environ["DC_E2E_OWNER_PASSWORD"]
    viewer_email = os.environ["DC_E2E_VIEWER_EMAIL"]
    viewer_pw = os.environ["DC_E2E_VIEWER_PASSWORD"]

    # ---------------------------------------------------------------- UI shell & headers
    anon = httpx.Client(base_url=base, timeout=60)
    r = anon.get("/login")
    check("UI /login served (HTML, no-store, CSP)",
          r.status_code == 200 and "text/html" in r.headers.get("content-type", "")
          and r.headers.get("cache-control") == "no-store"
          and "default-src 'self'" in r.headers.get("content-security-policy", ""))
    deep = anon.get("/w/000000000000000000000000/collections/000000000000000000000000/data")
    check("deep link refresh returns the SPA", deep.status_code == 200 and "<div id=\"root\">" in deep.text)
    import re

    m = re.search(r'src="(/assets/[^"]+\.js)"', r.text)
    if m:
        a = anon.get(m.group(1))
        check("hashed JS asset immutable + JS MIME",
              a.status_code == 200 and "immutable" in a.headers.get("cache-control", "")
              and "javascript" in a.headers.get("content-type", ""))
    check("unknown API path stays JSON 404", anon.get("/api/v1/nope").status_code == 404)
    check("anonymous /api/backend/me -> 401", anon.get("/api/backend/me").status_code == 401)

    # ---------------------------------------------------------------- login / session
    owner = Browser(base)
    r = owner.call("POST", "/api/auth/login", csrf=False, headers={"Origin": "https://evil.example"},
                   json={"email": owner_email, "password": owner_pw})
    check("login from foreign Origin rejected", r.status_code == 403)
    r = owner.login(owner_email, "wrong-password-123!")
    check("wrong password -> 401", r.status_code == 401)
    r = owner.login(owner_email, owner_pw)
    set_cookie = " | ".join(r.headers.get_list("set-cookie"))
    check("login OK", r.status_code == 200, f"status {r.status_code}")
    check("session cookie __Host- HttpOnly Secure SameSite=Lax",
          "__Host-dc_sid=" in set_cookie and "HttpOnly" in set_cookie and "Secure" in set_cookie
          and "SameSite=Lax" in set_cookie)
    check("no tokens in login response", "access_token" not in r.text and "refresh_token" not in r.text)
    me = owner.api("GET", "me")
    check("GET me through BFF", me.status_code == 200 and me.json().get("email") == owner_email)

    r = owner.api("POST", "workspaces", csrf=False, json={"slug": "x-no-csrf", "name": "x"})
    check("state change without CSRF -> 403", r.status_code == 403)
    r = owner.api("GET", "auth/login")
    check("non-allowlisted backend path -> 403", r.status_code == 403)

    # ---------------------------------------------------------------- workspace / project / collection
    slug = f"e2e-{uuid.uuid4().hex[:8]}"
    ws = owner.api("POST", "workspaces", json={"slug": slug, "name": "E2E " + slug})
    if not check("create workspace", ws.status_code == 201, str(ws.status_code)):
        return
    wid = ws.json()["id"]
    pr = owner.api("POST", f"workspaces/{wid}/projects", json={"slug": "proj-e2e", "name": "Project"})
    check("create project", pr.status_code == 201)
    pid = pr.json()["id"]
    col = owner.api("POST", f"projects/{pid}/collections", json={
        "slug": "leads-e2e",
        "schema_json": {"type": "object", "additionalProperties": False, "required": ["name"],
                        "properties": {"name": {"type": "string"}, "score": {"type": "integer"},
                                       "status": {"type": "string"}}},
        "searchable_fields": ["name", "status"],
    })
    check("create collection", col.status_code == 201, str(col.status_code))
    cid = col.json()["id"]

    # ---------------------------------------------------------------- records
    idem = {"Idempotency-Key": uuid.uuid4().hex}
    r1 = owner.api("POST", f"collections/{cid}/records", headers=idem,
                   json={"data": {"name": "Lead A", "score": 10, "status": "new"}})
    r2 = owner.api("POST", f"collections/{cid}/records", headers=idem,
                   json={"data": {"name": "Lead A", "score": 10, "status": "new"}})
    check("record create + Idempotency-Key replay",
          r1.status_code == 201 and r2.status_code in (200, 201) and r1.json()["id"] == r2.json()["id"])
    rid = r1.json()["id"]
    bad = owner.api("POST", f"collections/{cid}/records", json={"data": {"name": 1}})
    check("schema violation -> 422", bad.status_code == 422)
    conflict = owner.api("PATCH", f"collections/{cid}/records/{rid}",
                         json={"patch": {"score": 20}, "expected_version": 99})
    check("stale expected_version -> 409", conflict.status_code == 409)
    upd = owner.api("PATCH", f"collections/{cid}/records/{rid}",
                    json={"patch": {"score": 20}, "expected_version": 1})
    check("record update", upd.status_code == 200)
    srch = owner.api("POST", f"collections/{cid}/records/search",
                     json={"filter": {"field": "score", "op": "gte", "value": 15}})
    check("record search", srch.status_code == 200 and len(srch.json().get("items", [])) == 1)
    dl = owner.api("DELETE", f"collections/{cid}/records/{rid}", json={"expected_version": 2})
    check("record soft delete", dl.status_code in (200, 204), str(dl.status_code))
    trash = owner.api("GET", f"collections/{cid}/records/trash")
    check("trash lists deleted record", trash.status_code == 200
          and any(x.get("id") == rid for x in trash.json().get("items", [])))
    rs = owner.api("POST", f"collections/{cid}/records/{rid}/restore")
    check("record restore", rs.status_code == 200)

    # ---------------------------------------------------------------- async jobs (worker)
    body = b"".join(f'{{"name": "Imported {i}", "score": {i}, "status": "imp"}}\n'.encode() for i in range(25))
    imp = owner.api("POST", f"collections/{cid}/imports?format=jsonl", content=body,
                    headers={"Content-Type": "application/x-ndjson", "Idempotency-Key": uuid.uuid4().hex})
    check("import job accepted (202, queued for worker)",
          imp.status_code == 202 and imp.json().get("state") in ("queued", "running", "completed"),
          f"{imp.status_code} {imp.json().get('state') if imp.status_code == 202 else imp.text[:200]}")
    if imp.status_code == 202:
        job = wait_job(owner, imp.json()["id"])
        check("import job completed by worker", job.get("state") == "completed", str(job.get("state")))
    total = owner.api("GET", f"collections/{cid}/records?limit=100").json().get("items", [])
    check("records after import", len(total) == 26, str(len(total)))
    exp = owner.api("POST", f"collections/{cid}/exports", json={"format": "csv"})
    check("export job accepted", exp.status_code == 202)
    if exp.status_code == 202:
        job = wait_job(owner, exp.json()["id"])
        check("export job completed by worker", job.get("state") == "completed", str(job.get("state")))
        res = owner.api("GET", f"jobs/{exp.json()['id']}/result")
        digest = hashlib.sha256(res.content).hexdigest()
        check("export download: bytes, attachment, sha256 header",
              res.status_code == 200 and "attachment" in res.headers.get("content-disposition", "")
              and res.headers.get("x-content-sha256") == digest and res.content.count(b"\n") >= 26)

    # ---------------------------------------------------------------- keys / audit / analytics / webhooks
    k = owner.api("POST", "keys", json={"workspace_id": wid, "name": "e2e-reader",
                                         "scopes": ["collection:read", "records:read"]})
    check("API key created", k.status_code == 201)
    if k.status_code == 201:
        raw, kid = k.json()["api_key"], k.json()["id"]
        direct = httpx.get(f"{base}/api/v1/collections/{cid}/records", headers={"X-API-Key": raw}, timeout=30)
        check("API key works directly against /api/v1", direct.status_code == 200)
        denied = httpx.post(f"{base}/api/v1/collections/{cid}/records", headers={"X-API-Key": raw},
                            json={"data": {"name": "nope"}}, timeout=30)
        check("read-only key cannot write", denied.status_code == 403, str(denied.status_code))
        rv = owner.api("POST", f"keys/{kid}/revoke", json={"workspace_id": wid})
        check("API key revoked", rv.status_code == 200)
        gone = httpx.get(f"{base}/api/v1/collections/{cid}/records", headers={"X-API-Key": raw}, timeout=30)
        check("revoked key rejected", gone.status_code == 401)
    au = owner.api("GET", f"workspaces/{wid}/audit")
    check("audit log", au.status_code == 200 and len(au.json().get("items", [])) > 0)
    us = owner.api("GET", f"workspaces/{wid}/usage")
    check("usage analytics", us.status_code == 200)
    summ = owner.api("GET", f"workspaces/{wid}/dashboard/summary")
    check("dashboard summary", summ.status_code == 200)
    wh = owner.api("POST", f"workspaces/{wid}/webhooks",
                   json={"name": "e2e", "url": "https://example.com/dc-e2e-hook", "events": ["record.created"]})
    check("webhook create (public https target)", wh.status_code == 201, f"{wh.status_code} {wh.text[:160]}")
    ssrf = owner.api("POST", f"workspaces/{wid}/webhooks",
                     json={"name": "ssrf", "url": "http://127.0.0.1:27017/", "events": ["record.created"]})
    check("webhook SSRF to localhost rejected", ssrf.status_code in (400, 422), str(ssrf.status_code))
    if wh.status_code == 201:
        d = owner.api("DELETE", f"workspaces/{wid}/webhooks/{wh.json()['id']}")
        check("webhook delete", d.status_code in (200, 204))

    # ---------------------------------------------------------------- roles
    inv = owner.api("POST", f"workspaces/{wid}/invitations", json={"email": viewer_email, "role": "viewer"})
    check("invite viewer", inv.status_code == 201, str(inv.status_code))
    viewer = Browser(base)
    check("viewer login", viewer.login(viewer_email, viewer_pw).status_code == 200)
    if inv.status_code == 201:
        acc = viewer.api("POST", f"invitations/{inv.json()['id']}/accept", json={"token": inv.json()["invite_token"]})
        check("viewer accepts invitation", acc.status_code == 200, str(acc.status_code))
    caps = viewer.api("GET", f"workspaces/{wid}/capabilities")
    check("viewer capabilities role=viewer", caps.status_code == 200 and caps.json().get("role") == "viewer")
    check("viewer can read records", viewer.api("GET", f"collections/{cid}/records").status_code == 200)
    w = viewer.api("POST", f"collections/{cid}/records", json={"data": {"name": "viewer write"}})
    check("viewer cannot write records (403)", w.status_code == 403, str(w.status_code))
    k2 = viewer.api("POST", "keys", json={"workspace_id": wid, "name": "x", "scopes": ["records:read"]})
    check("viewer cannot create API keys (403)", k2.status_code == 403, str(k2.status_code))
    viewer.call("POST", "/api/auth/logout")

    # ---------------------------------------------------------------- refresh / logout / cleanup
    rf = owner.call("POST", "/api/auth/refresh")
    check("session refresh (rotation)", rf.status_code == 200)
    check("session works after rotation", owner.api("GET", "me").status_code == 200)
    arch = owner.api("POST", f"workspaces/{wid}/archive")
    check("cleanup: test workspace archived", arch.status_code == 200, str(arch.status_code))
    lo = owner.call("POST", "/api/auth/logout")
    check("logout", lo.status_code == 200)
    check("session invalid after logout", owner.api("GET", "me").status_code == 401)
    _ = host


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--resolve", help="pin the hostname to this IP")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    if args.resolve:
        pin_dns(urlparse(base).hostname or "", args.resolve)
    try:
        run(base)
    except Exception as exc:  # noqa: BLE001
        check("unexpected exception", False, f"{type(exc).__name__}: {exc}")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    _: Callable[[], int] = main
    sys.exit(main())
