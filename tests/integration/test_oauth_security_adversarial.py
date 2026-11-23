"""Adversarial security tests for OAuth 2.1, durable keys, consent/CSRF, refresh, SSRF."""

from __future__ import annotations

import base64
import hashlib
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import fakeredis
import httpx
import jwt as pyjwt
import mongomock
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from data_collector.config import Settings
from data_collector.container import build_container
from data_collector.domain.exceptions import ValidationError
from data_collector.infrastructure.oauth import OAuthService
from data_collector.infrastructure.ssrf import post_webhook_safe, resolve_and_pin_url
from data_collector.mcp.server_http import create_mcp_http_app
from pydantic import ValidationError as PydanticValidationError
from starlette.testclient import TestClient


def _generate_rsa_pem(bits: int = 2048) -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")


def test_sec01_durable_key_enforcement_and_multi_instance_consistency():
    # Production builtin without durable key fails fast
    with pytest.raises(PydanticValidationError, match="OAUTH_RSA_PRIVATE_KEY_PEM"):
        Settings(
            app_env="production",
            jwt_secret_key="p" * 40,
            allowed_origins=["https://app.example.com"],
            mcp_public_url="https://collector.example.com/mcp",
            auth_issuer="https://collector.example.com",
            oauth_mode="builtin",
            oauth_rsa_private_key_pem="",
        )

    # Production external without HTTPS JWKS fails fast
    with pytest.raises(PydanticValidationError, match="OAUTH_JWKS_URL"):
        Settings(
            app_env="production",
            jwt_secret_key="p" * 40,
            allowed_origins=["https://app.example.com"],
            mcp_public_url="https://collector.example.com/mcp",
            auth_issuer="https://idp.example.com",
            oauth_mode="external",
            oauth_jwks_url="http://idp.example.com/jwks.json",
        )

    # Weak 1024-bit RSA key rejected without leaking PEM
    weak_pem = _generate_rsa_pem(1024)
    with pytest.raises(PydanticValidationError, match="2048") as exc_info:
        Settings(
            app_env="test",
            jwt_secret_key="t" * 40,
            oauth_rsa_private_key_pem=weak_pem,
        )
    assert "BEGIN PRIVATE KEY" not in str(exc_info.value)

    # Two instances with the same durable PEM share kid/JWKS and validate each other's tokens
    pem = _generate_rsa_pem(2048)
    s = Settings(
        app_env="production",
        jwt_secret_key="p" * 40,
        allowed_origins=["https://chatgpt.com"],
        mcp_public_url="https://collector.example.com/mcp",
        auth_issuer="https://collector.example.com",
        oauth_mode="builtin",
        oauth_rsa_private_key_pem=pem,
    )
    db = mongomock.MongoClient()["oauth_multi"]
    svc1 = OAuthService(s, db)
    svc2 = OAuthService(s, db)
    assert svc1.jwks() == svc2.jwks()

    tok_bundle = svc1._mint_oauth_tokens(
        user_id="u1",
        email="u1@example.com",
        client_id="c1",
        scopes=["workspace:read"],
        resource=s.mcp_public_url,
        family_id="fam1",
    )
    actor = svc2.verify_bearer_token(tok_bundle["access_token"])
    assert actor.principal_id == "u1"


def test_sec02_sec03_sec05_consent_csrf_scope_refresh_and_safe_revocation():
    pem = _generate_rsa_pem(2048)
    settings = Settings(
        app_env="test",
        jwt_secret_key="t" * 40,
        allowed_origins=["https://chatgpt.com"],
        mcp_public_url="https://collector.example.com/mcp",
        auth_issuer="https://collector.example.com",
        oauth_mode="builtin",
        oauth_rsa_private_key_pem=pem,
    )
    ctr = build_container(
        settings,
        mongo_client=mongomock.MongoClient(),
        redis_client=fakeredis.FakeRedis(),
        ensure_indexes=True,
    )
    ctr.auth_service.register_user("victim@example.com", "StrongPassword123!")
    app = create_mcp_http_app(settings, container=ctr)
    client = TestClient(app)

    # Register client with read-only scopes
    reg = client.post(
        "/oauth/register",
        json={
            "client_name": "ReaderApp",
            "redirect_uris": ["https://chatgpt.com/aip/oauth/callback"],
            "scope": "workspace:read records:read",
        },
    ).json()
    cid = reg["client_id"]
    verifier = "a" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )

    # Escalated scope request (records:delete) denied on authorize
    esc = client.get(
        "/oauth/authorize",
        params={
            "client_id": cid,
            "redirect_uri": "https://chatgpt.com/aip/oauth/callback",
            "scope": "records:read records:delete",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert esc.status_code == 400

    # Valid GET /oauth/authorize issues CSRF cookie + consent page
    get_auth = client.get(
        "/oauth/authorize",
        params={
            "client_id": cid,
            "redirect_uri": "https://chatgpt.com/aip/oauth/callback",
            "scope": "workspace:read records:read",
            "state": "s1",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert get_auth.status_code == 200
    assert "Authorize MCP Client" in get_auth.text
    csrf_cookie = client.cookies.get("dc_oauth_csrf")
    assert csrf_cookie

    # Forged CSRF rejected
    forged_csrf = client.post(
        "/oauth/authorize",
        data={
            "csrf_token": "forged.token",
            "client_id": cid,
            "redirect_uri": "https://chatgpt.com/aip/oauth/callback",
            "scope": "workspace:read records:read",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "email": "victim@example.com",
            "password": "StrongPassword123!",
        },
    )
    assert forged_csrf.status_code == 403

    # Consent Deny -> error=access_denied, no code
    denied = client.post(
        "/oauth/authorize",
        data={
            "csrf_token": csrf_cookie,
            "consent": "deny",
            "client_id": cid,
            "redirect_uri": "https://chatgpt.com/aip/oauth/callback",
            "state": "s1",
            "scope": "workspace:read records:read",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert denied.status_code == 302
    assert "error=access_denied" in denied.headers["location"]

    # Consent Approve -> code issued
    approved = client.post(
        "/oauth/authorize",
        data={
            "csrf_token": csrf_cookie,
            "consent": "approve",
            "client_id": cid,
            "redirect_uri": "https://chatgpt.com/aip/oauth/callback",
            "state": "s1",
            "scope": "workspace:read records:read",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "email": "victim@example.com",
            "password": "StrongPassword123!",
        },
        follow_redirects=False,
    )
    assert approved.status_code == 302
    code = parse_qs(urlparse(approved.headers["location"]).query)["code"][0]

    # SEC-05a: Attacker with wrong verifier does NOT invalidate code for legitimate client
    bad_exchange = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": cid,
            "redirect_uri": "https://chatgpt.com/aip/oauth/callback",
            "code_verifier": "wrong" * 12,
        },
    )
    assert bad_exchange.status_code == 400

    # Legitimate client still redeems code successfully
    good_exchange = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": cid,
            "redirect_uri": "https://chatgpt.com/aip/oauth/callback",
            "code_verifier": verifier,
        },
    )
    assert good_exchange.status_code == 200
    tok1 = good_exchange.json()
    assert "refresh_token" in tok1

    # SEC-03: Refresh token rotation + replay family revocation
    ref1 = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tok1["refresh_token"],
            "client_id": cid,
        },
    )
    assert ref1.status_code == 200
    tok2 = ref1.json()
    assert tok2["refresh_token"] != tok1["refresh_token"]

    # Replay of tok1 revokes family -> tok2 also fails
    replay = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tok1["refresh_token"],
            "client_id": cid,
        },
    )
    assert replay.status_code == 400
    after_replay = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tok2["refresh_token"],
            "client_id": cid,
        },
    )
    assert after_replay.status_code == 400

    # SEC-05b: Attacker forging a JWT with victim's jti cannot revoke victim's access token
    victim_claims = pyjwt.decode(tok2["access_token"], options={"verify_signature": False})
    attacker_forged = pyjwt.encode(
        {"jti": victim_claims["jti"], "client_id": cid},
        "attacker-key",
        algorithm="HS256",
    )
    client.post("/oauth/revoke", data={"token": attacker_forged, "client_id": cid})
    assert (
        ctr.oauth_service.verify_bearer_token(tok2["access_token"]).principal_id
        == victim_claims["sub"]
    )

    # Legitimate revocation with matching client_id succeeds
    client.post("/oauth/revoke", data={"token": tok2["access_token"], "client_id": cid})
    with pytest.raises(Exception, match="revoked"):
        ctr.oauth_service.verify_bearer_token(tok2["access_token"])
    ctr.close()


def test_sec04_ssrf_dns_pinning_and_ipv6_mapped():
    # IPv4-mapped IPv6 loopback rejected
    with pytest.raises(ValidationError):
        resolve_and_pin_url("https://[::ffff:127.0.0.1]/hook")

    # DNS rebinding defense: transport connects to pinned public IP from single getaddrinfo call
    fake_addr = [(2, 1, 6, "", ("93.184.216.34", 443))]
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.post.return_value = MagicMock(status_code=200)
    with patch("data_collector.infrastructure.ssrf.socket.getaddrinfo", return_value=fake_addr):
        code = post_webhook_safe(
            "https://hooks.example.com/ingest",
            content=b'{"ok":true}',
            headers={"Content-Type": "application/json"},
            http_client=mock_http,
        )
    assert code == 200
    called_url = mock_http.post.call_args.args[0]
    assert called_url.startswith("https://93.184.216.34:443/")
    assert mock_http.post.call_args.kwargs["extensions"]["sni_hostname"] == "hooks.example.com"
