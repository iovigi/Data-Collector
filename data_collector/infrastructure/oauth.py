"""Standards-compliant OAuth 2.1 (Authorization Code + PKCE S256, RS256 JWKS, RFC 7591)."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from pymongo.database import Database

from data_collector.config import Settings
from data_collector.domain.exceptions import AuthenticationError, BadRequestError, ValidationError
from data_collector.domain.identities import Actor, PrincipalType, Scope
from data_collector.infrastructure.crypto import hash_token


def _b64url_uint(val: int) -> str:
    raw = val.to_bytes((val.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_pkce_s256(code_verifier: str, code_challenge: str) -> bool:
    """Verify RFC 7636 PKCE S256 challenge."""
    if not code_verifier or len(code_verifier) < 43 or len(code_verifier) > 128:
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return secrets.compare_digest(computed, code_challenge)


def validate_redirect_uri(uri: str) -> str:
    """Validate OAuth redirect URI (HTTPS required, except localhost/127.0.0.1 for local dev)."""
    parsed = urlparse(uri)
    if parsed.scheme == "https" and parsed.netloc:
        return uri
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
        return uri
    raise ValidationError("redirect_uri must use https (or http://localhost for local dev)")


class OAuthService:
    """Builtin OAuth 2.1 provider and RS256/JWKS token verifier."""

    def __init__(self, settings: Settings, db: Database[Any]) -> None:
        self._settings = settings
        self._clients = db.oauth_clients
        self._codes = db.oauth_codes
        self._revoked = db.oauth_revoked_jtis
        self._jwk_client: PyJWKClient | None = None

        if settings.oauth_mode == "external" and settings.oauth_jwks_url:
            self._jwk_client = PyJWKClient(settings.oauth_jwks_url)

        if settings.oauth_rsa_private_key_pem.strip():
            self._private_key = serialization.load_pem_private_key(
                settings.oauth_rsa_private_key_pem.encode("utf-8"),
                password=None,
            )
        else:
            self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        self._public_key = self._private_key.public_key()  # type: ignore[union-attr]
        pub_pem = self._public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self._kid = hashlib.sha256(pub_pem).hexdigest()[:16]

    def jwks(self) -> dict[str, Any]:
        """Return RFC 7517 JWKS containing the active RS256 public key."""
        numbers = self._public_key.public_numbers()  # type: ignore[union-attr]
        assert isinstance(numbers, rsa.RSAPublicNumbers)
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": self._kid,
                    "n": _b64url_uint(numbers.n),
                    "e": _b64url_uint(numbers.e),
                }
            ]
        }

    def register_client(
        self,
        *,
        client_name: str,
        redirect_uris: list[str],
        scope: str = "workspace:read collection:read records:read",
    ) -> dict[str, Any]:
        """RFC 7591 Dynamic Client Registration (public PKCE clients)."""
        if not redirect_uris:
            raise ValidationError("At least one redirect_uri is required")
        validated_uris = [validate_redirect_uri(u) for u in redirect_uris]
        client_id = f"dc_oauth_{secrets.token_hex(12)}"
        doc = {
            "client_id": client_id,
            "client_name": client_name[:120],
            "redirect_uris": validated_uris,
            "scope": scope,
            "token_endpoint_auth_method": "none",
            "created_at": datetime.now(UTC),
        }
        self._clients.insert_one(doc)
        return {
            "client_id": client_id,
            "client_name": doc["client_name"],
            "redirect_uris": validated_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        }

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return self._clients.find_one({"client_id": client_id})

    def create_authorization_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        user_id: str,
        email: str,
        scopes: list[str],
        code_challenge: str,
        code_challenge_method: str,
        resource: str | None = None,
    ) -> str:
        """Validate client/PKCE parameters and issue a single-use authorization code."""
        client = self.get_client(client_id)
        if client is None:
            raise BadRequestError("Unknown client_id")
        if redirect_uri not in client.get("redirect_uris", []):
            raise BadRequestError("redirect_uri is not registered for this client")
        if code_challenge_method != "S256" or not code_challenge:
            raise BadRequestError("PKCE code_challenge_method=S256 is required")

        target_resource = resource or self._settings.mcp_public_url
        if target_resource != self._settings.mcp_public_url:
            raise BadRequestError("Requested resource does not match this MCP server")

        code = secrets.token_urlsafe(32)
        self._codes.insert_one(
            {
                "code_hash": hash_token(code),
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "user_id": user_id,
                "email": email,
                "scopes": scopes,
                "code_challenge": code_challenge,
                "resource": target_resource,
                "used": False,
                "expires_at": datetime.now(UTC) + timedelta(minutes=5),
            }
        )
        return code

    def exchange_code(
        self,
        *,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict[str, Any]:
        """Atomically consume authorization code, verify PKCE S256, and mint RS256 access token."""
        doc = self._codes.find_one_and_update(
            {"code_hash": hash_token(code), "used": False},
            {"$set": {"used": True}},
        )
        if doc is None:
            raise AuthenticationError("Invalid or already-used authorization code")
        if doc["client_id"] != client_id or doc["redirect_uri"] != redirect_uri:
            raise AuthenticationError("Client or redirect_uri mismatch")
        exp = doc["expires_at"]
        if isinstance(exp, datetime):
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp < datetime.now(UTC):
                raise AuthenticationError("Authorization code expired")
        if not verify_pkce_s256(code_verifier, doc["code_challenge"]):
            raise AuthenticationError("Invalid PKCE code_verifier")

        return self._mint_oauth_tokens(
            user_id=doc["user_id"],
            email=doc["email"],
            client_id=client_id,
            scopes=doc["scopes"],
            resource=doc["resource"],
        )

    def _mint_oauth_tokens(
        self,
        *,
        user_id: str,
        email: str,
        client_id: str,
        scopes: list[str],
        resource: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        jti = secrets.token_hex(12)
        issuer = self._settings.auth_issuer.rstrip("/")
        payload = {
            "sub": user_id,
            "email": email,
            "client_id": client_id,
            "iss": issuer,
            "aud": resource,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(
                (now + timedelta(seconds=self._settings.access_token_ttl_seconds)).timestamp()
            ),
            "jti": jti,
            "scope": " ".join(scopes),
            "scopes": scopes,
        }
        access_token = jwt.encode(
            payload,
            self._private_key,  # type: ignore[arg-type]
            algorithm="RS256",
            headers={"kid": self._kid},
        )
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": self._settings.access_token_ttl_seconds,
            "scope": " ".join(scopes),
        }

    def revoke_token(self, token: str) -> None:
        """Revoke an OAuth access token by its jti."""
        with contextlib.suppress(Exception):
            unverified = jwt.decode(token, options={"verify_signature": False})
            jti = unverified.get("jti")
            if isinstance(jti, str) and jti:
                self._revoked.update_one(
                    {"jti": jti},
                    {"$set": {"revoked_at": datetime.now(UTC)}},
                    upsert=True,
                )

    def verify_bearer_token(self, token: str, *, is_mcp: bool = True) -> Actor:
        """Verify RS256/ES256 OAuth access token bound strictly to MCP_PUBLIC_URL."""
        issuer = self._settings.auth_issuer.rstrip("/")
        audience = self._settings.mcp_public_url
        try:
            if self._settings.oauth_mode == "external":
                if self._jwk_client is None:
                    raise AuthenticationError("External JWKS URL is not configured")
                signing_key = self._jwk_client.get_signing_key_from_jwt(token)
                payload = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256", "ES256"],
                    issuer=issuer,
                    audience=audience,
                )
            else:
                payload = jwt.decode(
                    token,
                    self._public_key,  # type: ignore[arg-type]
                    algorithms=["RS256"],
                    issuer=issuer,
                    audience=audience,
                )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Invalid, expired, or wrong-audience OAuth token") from exc

        jti = payload.get("jti")
        if isinstance(jti, str) and self._revoked.find_one({"jti": jti}) is not None:
            raise AuthenticationError("OAuth token has been revoked")

        sub = payload.get("sub")
        if not isinstance(sub, str) or not sub:
            raise AuthenticationError("OAuth token missing subject")

        raw_scopes = payload.get("scopes")
        if not isinstance(raw_scopes, list):
            scope_str = str(payload.get("scope", ""))
            raw_scopes = [s for s in scope_str.split() if s]

        parsed_scopes: set[Scope] = set()
        for s in raw_scopes:
            with contextlib.suppress(ValueError):
                parsed_scopes.add(Scope(s))

        return Actor(
            principal_id=sub,
            principal_type=PrincipalType.OAUTH_CLIENT,
            email=payload.get("email"),
            scopes=frozenset(parsed_scopes),
            client_id=payload.get("client_id"),
            is_mcp=is_mcp,
            mcp_allow_writes=self._settings.mcp_allow_writes,
        )
