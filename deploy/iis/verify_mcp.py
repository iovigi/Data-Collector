"""MCP acceptance test against the deployed public endpoint (OAuth 2.1 + real MCP SDK client).

    set DC_E2E_OWNER_EMAIL / _PASSWORD, DC_E2E_VIEWER_EMAIL / _PASSWORD
    python verify_mcp.py https://data.devart.solutions [--resolve <edge-ip>]

Flow per user: dynamic client registration -> authorize (consent form + CSRF cookie,
PKCE S256, resource indicator) -> code exchange -> MCP initialize / tools/list / tools/call
with the official SDK client -> refresh rotation + replay detection -> revocation.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import sys
import uuid
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

RESULTS: list[tuple[str, bool, str]] = []
# Production accepts https redirect URIs only; use the callback Claude.ai registers.
REDIRECT = "https://claude.ai/api/mcp/auth_callback"
SCOPE = "workspace:read collection:read records:read"


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -- ' + detail) if detail else ''}")
    return ok


def oauth_login(base: str, email: str, password: str, label: str) -> dict[str, Any]:
    c = httpx.Client(base_url=base, timeout=60, follow_redirects=False)
    reg = c.post("/oauth/register", json={"client_name": f"dc-verify-{label}",
                                          "redirect_uris": [REDIRECT], "scope": SCOPE})
    check(f"[{label}] dynamic client registration", reg.status_code == 201, str(reg.status_code))
    client_id = reg.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(12)
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "scope": SCOPE,
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
         "resource": f"{base}/mcp"}
    page = c.get("/oauth/authorize?" + urlencode(q))
    csrf_cookie = " ".join(page.headers.get_list("set-cookie"))
    check(f"[{label}] consent page + Secure HttpOnly CSRF cookie",
          page.status_code == 200 and "Approve" in page.text and "Secure" in csrf_cookie
          and "HttpOnly" in csrf_cookie)
    token = re.search(r"name='csrf_token' value='([^']+)'", page.text).group(1)  # type: ignore[union-attr]

    no_csrf = c.post("/oauth/authorize", data={**q, "email": email, "password": password,
                                               "consent": "approve", "csrf_token": "x.y"})
    check(f"[{label}] consent without valid CSRF rejected", no_csrf.status_code == 403)
    post = c.post("/oauth/authorize", data={**q, "csrf_token": token, "email": email,
                                            "password": password, "consent": "approve"})
    loc = post.headers.get("location", "")
    qs = parse_qs(urlparse(loc).query)
    check(f"[{label}] authorization code redirect with state",
          post.status_code == 302 and loc.startswith(REDIRECT) and qs.get("state") == [state] and "code" in qs)
    code = qs["code"][0]
    bad = c.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
                                       "client_id": client_id, "redirect_uri": REDIRECT,
                                       "code_verifier": "wrong-" + verifier})
    check(f"[{label}] PKCE verifier mismatch rejected", bad.status_code == 400)
    tok = c.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
                                       "client_id": client_id, "redirect_uri": REDIRECT,
                                       "code_verifier": verifier})
    if not check(f"[{label}] code exchange", tok.status_code == 200, f"{tok.status_code} {tok.text[:150]}"):
        # PKCE failure may have consumed the code: run a fresh authorization once
        raise SystemExit(1)
    return {"client": c, "client_id": client_id, **tok.json()}


async def mcp_session(base: str, token: str, probe_col: str) -> tuple[list[str], dict, dict]:
    async with (
        httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=60) as http,
        streamable_http_client(f"{base}/mcp", http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = [t.name for t in (await session.list_tools()).tools]
        ws = json.loads((await session.call_tool("dc_list_workspaces", {})).content[0].text)
        probe = json.loads((await session.call_tool("dc_search_records",
                                                    {"collection_id": probe_col})).content[0].text)
        return tools, ws, probe


def setup_owner_data(base: str, email: str, password: str) -> tuple[str, str, str]:
    c = httpx.Client(base_url=base, timeout=60)
    c.post("/api/auth/login", headers={"Origin": base}, json={"email": email, "password": password})
    h = {"Origin": base, "X-CSRF-Token": c.cookies.get("__Host-dc_csrf") or ""}
    ws = c.post("/api/backend/workspaces", headers=h, json={"slug": f"mcp-{uuid.uuid4().hex[:8]}", "name": "MCP"}).json()
    pr = c.post(f"/api/backend/workspaces/{ws['id']}/projects", headers=h, json={"slug": "mcp-proj", "name": "P"}).json()
    col = c.post(f"/api/backend/projects/{pr['id']}/collections", headers=h, json={
        "slug": "mcp-col", "searchable_fields": ["note"],
        "schema_json": {"type": "object", "properties": {"note": {"type": "string"}}}}).json()
    c.post(f"/api/backend/collections/{col['id']}/records", headers=h, json={"data": {"note": "OWNER_ONLY_SECRET"}})
    return ws["id"], col["id"], json.dumps(dict(c.cookies))


def run(base: str) -> None:
    anon = httpx.Client(base_url=base, timeout=60)
    prm = anon.get("/.well-known/oauth-protected-resource").json()
    check("protected-resource metadata (public https resource)",
          prm.get("resource") == f"{base}/mcp" and prm.get("authorization_servers") == [base])
    asm = anon.get("/.well-known/oauth-authorization-server").json()
    check("authorization-server metadata consistent",
          asm.get("issuer") == base and asm.get("token_endpoint") == f"{base}/oauth/token"
          and asm.get("code_challenge_methods_supported") == ["S256"])
    jwks = anon.get(asm["jwks_uri"]).json()
    check("JWKS reachable (RSA key)", any(k.get("kty") == "RSA" for k in jwks.get("keys", [])))
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "probe", "version": "1"}}}
    r = anon.post("/mcp", json=init, headers={"Accept": "application/json, text/event-stream"})
    check("unauthenticated MCP POST -> 401 + WWW-Authenticate (no HTML)",
          r.status_code == 401 and f'resource_metadata="{base}/.well-known/oauth-protected-resource"'
          in r.headers.get("www-authenticate", "") and "<html" not in r.text.lower())
    check("GET /mcp -> 405 (stateless, no SSE stream)", anon.get("/mcp").status_code == 405)

    owner_email, owner_pw = os.environ["DC_E2E_OWNER_EMAIL"], os.environ["DC_E2E_OWNER_PASSWORD"]
    viewer_email, viewer_pw = os.environ["DC_E2E_VIEWER_EMAIL"], os.environ["DC_E2E_VIEWER_PASSWORD"]
    wid, cid, _ = setup_owner_data(base, owner_email, owner_pw)

    owner = oauth_login(base, owner_email, owner_pw, "owner")
    other = oauth_login(base, viewer_email, viewer_pw, "other-user")

    async def both():
        return await asyncio.gather(mcp_session(base, owner["access_token"], cid),
                                    mcp_session(base, other["access_token"], cid))

    (t1, ws1, p1), (t2, ws2, p2) = asyncio.run(both())
    check("SDK initialize + tools/list via IIS",
          {"dc_list_workspaces", "dc_search_records"} <= set(t1) and set(t1) == set(t2), f"{len(t1)} tools")
    check("owner sees own workspace", wid in [w["id"] for w in ws1.get("items", [])])
    check("other user does not see owner's workspace", wid not in [w["id"] for w in ws2.get("items", [])])
    check("owner reads own record via dc_search_records",
          p1.get("ok") is True and "OWNER_ONLY_SECRET" in json.dumps(p1))
    check("parallel other user cannot read owner's records",
          p2.get("ok") is False and "OWNER_ONLY_SECRET" not in json.dumps(p2))

    oc: httpx.Client = owner["client"]
    rot = oc.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": owner["refresh_token"],
                                        "client_id": owner["client_id"]})
    check("refresh token rotation", rot.status_code == 200 and rot.json()["refresh_token"] != owner["refresh_token"])
    replay = oc.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": owner["refresh_token"],
                                           "client_id": owner["client_id"]})
    check("refresh token replay rejected", replay.status_code == 400)
    if rot.status_code == 200:
        newest = rot.json()["refresh_token"]
        after_replay = oc.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": newest,
                                                     "client_id": owner["client_id"]})
        check("replay revoked the whole token family", after_replay.status_code == 400)
    oth: httpx.Client = other["client"]
    rv = oth.post("/oauth/revoke", data={"token": other["refresh_token"], "client_id": other["client_id"]})
    check("revocation endpoint", rv.status_code == 200)
    after = oth.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": other["refresh_token"],
                                           "client_id": other["client_id"]})
    check("revoked refresh token unusable", after.status_code == 400)
    cache = anon.post("/mcp", json=init, headers={"Accept": "application/json"})
    cf = cache.headers.get("cf-cache-status", "(no header)")
    check("MCP responses not cached at the edge", cf in ("DYNAMIC", "BYPASS", "(no header)"), cf)

    # cleanup through the BFF
    c = httpx.Client(base_url=base, timeout=60)
    c.post("/api/auth/login", headers={"Origin": base}, json={"email": owner_email, "password": owner_pw})
    h = {"Origin": base, "X-CSRF-Token": c.cookies.get("__Host-dc_csrf") or ""}
    check("cleanup: MCP test workspace archived",
          c.post(f"/api/backend/workspaces/{wid}/archive", headers=h).status_code == 200)
    c.post("/api/auth/logout", headers=h)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--resolve")
    a = ap.parse_args()
    base = a.base_url.rstrip("/")
    if a.resolve:
        real = socket.getaddrinfo
        host = urlparse(base).hostname
        socket.getaddrinfo = lambda h, *x, **k: real(a.resolve if h == host else h, *x, **k)  # type: ignore[assignment]
    try:
        run(base)
    except SystemExit:
        pass
    except Exception as exc:  # noqa: BLE001
        check("unexpected exception", False, f"{type(exc).__name__}: {exc}")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
